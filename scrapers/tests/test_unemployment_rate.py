#!/usr/bin/env python3
"""Tests for scrapers/abs_series.py and scrapers/unemployment_rate.py. Plain asserts, no pytest.

Run from the project folder:  python3 scrapers/tests/test_unemployment_rate.py

No network. Small trimmed copies of the real ABS files are in fixtures/ (ten months, November 2019
to August 2020: the API response, Table 1 and the latest-release page). Variants for the refusal
cases are made in the tests by editing those bytes or building a small workbook.
"""
import io
import json
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import abs_series as a  # noqa: E402
import openpyxl  # noqa: E402
import unemployment_rate as ur  # noqa: E402

FX = HERE / "fixtures"
API = (FX / "abs-lf-api-trimmed.csv").read_bytes()
XLSX = (FX / "abs-lf-table1-trimmed.xlsx").read_bytes()
HTML = (FX / "abs-lf-latest-release.html").read_bytes()
quiet = lambda msg: None  # noqa: E731
SHEET_URL = "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/oct-2026/62020001.xlsx"


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {getattr(fn, '__name__', fn)}")


def api_with(old, new, count=1):
    text = API.decode()
    assert old in text
    return text.replace(old, new, count).encode()


def api_without(period):
    return "\n".join(l for l in API.decode().splitlines() if f",{period}," not in l).encode() + b"\n"


def make_sheet(rows, sid="A84423050A", description="Unemployment rate ;  Persons ;", series_type="Seasonally Adjusted", unit="Percent"):
    """A small workbook shaped like Table 1. rows is [(datetime, value)]."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data1"
    ws.append([None, "Employed total ;  Persons ;", description])
    ws.append(["Unit", "000", unit])
    ws.append(["Series Type", "Seasonally Adjusted", series_type])
    ws.append(["Data Type", "STOCK", "PERCENT"])
    ws.append(["Frequency", "Month", "Month"])
    ws.append(["Collection Month", 1, 1])
    ws.append(["Series Start", rows[0][0], rows[0][0]])
    ws.append(["Series End", rows[-1][0], rows[-1][0]])
    ws.append(["No. Obs", len(rows), len(rows)])
    ws.append(["Series ID", "A84423043C", sid])
    for d, v in rows:
        ws.append([d, 12000.5, v])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sheet_rows():
    """The fixture's own rows, as [(datetime, value)]."""
    wb = openpyxl.load_workbook(io.BytesIO(XLSX), data_only=True)
    return [(r[0], r[2]) for r in wb["Data1"].iter_rows(min_row=11, values_only=True)]


def fake_fetcher(api=API, html=HTML, xlsx=XLSX, calls=None):
    def f(url, accept="*/*"):
        if calls is not None:
            calls.append(url)
        if url == ur.API_URL:
            return api
        if url == ur.LATEST_URL:
            return html
        if url == SHEET_URL:
            return xlsx
        raise AssertionError(f"unexpected download {url}")
    return f


# ---------------------------------------------------------------- rounding

def test_rounding_is_half_up_not_bankers():
    assert a.round_half_up("5.25", 1) == "5.3"
    assert a.round_half_up("5.35", 1) == "5.4"
    assert a.round_half_up("5.05", 1) == "5.1"
    assert a.round_half_up("5.04999", 1) == "5.0"
    assert a.round_half_up("6.64467408", 1) == "6.6"
    assert a.round_half_up("4.0", 1) == "4.0"
    assert a.round_half_up("4", 1) == "4.0"
    assert a.round_half_up("4.5", 0) == "5"
    assert a.round_half_up("-0.04", 1) == "0.0"


def test_rounding_refuses_junk():
    raises(a.round_half_up, "abc", 1)
    raises(a.round_half_up, "NaN", 1)
    raises(a.round_half_up, "5.1", 9)


def test_month_end_handles_leap_years():
    assert a.month_end("1978-02") == "1978-02-28"
    assert a.month_end("2020-02") == "2020-02-29"
    assert a.month_end("1900-02") == "1900-02-28"
    assert a.month_end("2000-02") == "2000-02-29"
    assert a.month_end("2026-10") == "2026-10-31"
    assert a.month_end("2026-11") == "2026-11-30"
    raises(a.month_end, "2026-13")


# ---------------------------------------------------------------- the API response

def test_parse_api_fixture():
    s = a.parse_sdmx_series(API, ur.EXPECTED)
    assert len(s.pairs) == 10
    assert s.pairs[0][0] == "2019-11" and s.pairs[-1][0] == "2020-08"
    d = dict(s.pairs)
    assert d["2019-12"] == "5.0"        # from 5.03842...
    assert d["2020-04"] == "6.3"        # 6.307... in the fixture file
    assert all(len(v.split(".")[1]) == 1 for v in d.values())


def test_api_rows_in_any_order_give_the_same_result():
    lines = API.decode().splitlines()
    shuffled = "\n".join([lines[0]] + lines[1:][::-1]) + "\n"
    assert a.parse_sdmx_series(shuffled.encode(), ur.EXPECTED).pairs == a.parse_sdmx_series(API, ur.EXPECTED).pairs


def test_refuse_unexpected_dimension_codes():
    for col, old, new in (("MEASURE", ",M13,", ",M12,"), ("SEX", ",3,1599,", ",1,1599,"), ("AGE", ",1599,", ",1600,"),
                          ("TSEST", ",20,AUS", ",10,AUS"), ("REGION", ",AUS,M,", ",1,M,"), ("FREQ", ",AUS,M,", ",AUS,Q,")):
        msg = raises(a.parse_sdmx_series, api_with(old, new), ur.EXPECTED)
        assert col in msg and "not the series asked for" in msg, msg


def test_refuse_wrong_dataflow_and_unit():
    raises(a.parse_sdmx_series, api_with("ABS:LF(1.0.0)", "ABS:CPI(1.0.0)"), ur.EXPECTED)
    assert "UNIT_MEASURE" in raises(a.parse_sdmx_series, api_with(",PCT,", ",AUD,"), ur.EXPECTED)


def test_refuse_missing_columns():
    text = API.decode().replace("DECIMALS", "DECIMAL")
    assert "DECIMALS" in raises(a.parse_sdmx_series, text.encode(), ur.EXPECTED)
    text = API.decode().replace(",SEX,", ",GENDER,")
    assert "SEX" in raises(a.parse_sdmx_series, text.encode(), ur.EXPECTED)


def test_refuse_duplicate_month():
    lines = API.decode().splitlines()
    dup = "\n".join(lines + [lines[3]]) + "\n"
    assert "appears twice" in raises(a.parse_sdmx_series, dup.encode(), ur.EXPECTED)


def test_refuse_missing_month_inside_the_series():
    msg = raises(a.parse_sdmx_series, api_without("2020-03"), ur.EXPECTED)
    assert "missing months 2020-03" in msg


def test_a_missing_first_or_last_month_is_not_a_gap():
    # Trimming the ends leaves a valid shorter series; the row-count check against the old file catches that.
    assert len(a.parse_sdmx_series(api_without("2019-11"), ur.EXPECTED).pairs) == 9
    assert len(a.parse_sdmx_series(api_without("2020-08"), ur.EXPECTED).pairs) == 9


def test_refuse_unreadable_value():
    for bad in ("abc", "", "1e2", "NaN", "5.1.2"):
        text = API.decode().replace("5.0384235", bad)
        if bad == "":
            text = API.decode()
            # blank the OBS_VALUE of 2019-12
            lines = [l.split(",") for l in text.splitlines()]
            for l in lines:
                if l[7] == "2019-12":
                    l[8] = ""
            text = "\n".join(",".join(l) for l in lines)
        else:
            lines = [l.split(",") for l in API.decode().splitlines()]
            for l in lines:
                if l[7] == "2019-12":
                    l[8] = bad
            text = "\n".join(",".join(l) for l in lines)
        assert "unreadable value" in raises(a.parse_sdmx_series, text.encode(), ur.EXPECTED), bad


def test_refuse_unreadable_decimals_and_periods():
    assert "DECIMALS" in raises(a.parse_sdmx_series, api_with(",PCT,0,,,1", ",PCT,0,,,x"), ur.EXPECTED)
    assert "unexpected period" in raises(a.parse_sdmx_series, api_with("2019-12", "2019-Q4"), ur.EXPECTED)


def test_refuse_a_response_that_is_not_text():
    raises(a.parse_sdmx_series, b"\xff\xfe\x00\x01", ur.EXPECTED)


def test_fetch_refuses_non_200():
    class R:
        status_code = 503
        content = b""

    orig = a.requests.get
    a.requests.get = lambda *args, **kw: R()
    try:
        assert "HTTP 503" in raises(a.fetch, "https://example.invalid/x")
    finally:
        a.requests.get = orig


# ---------------------------------------------------------------- the link and the spreadsheet

def test_find_link_takes_the_62020001_link():
    assert a.find_link(HTML, ur.LATEST_URL, ur.SHEET_ENDING) == SHEET_URL


def test_find_link_refuses_none_two_or_foreign():
    raises(a.find_link, b"<a href='/x/6202.0'>no</a>", ur.LATEST_URL, ur.SHEET_ENDING)
    two = HTML + b'<a href="/statistics/labour/other/nov-2026/62020001.xlsx">x</a>'
    assert "more than one" in raises(a.find_link, two, ur.LATEST_URL, ur.SHEET_ENDING)
    raises(a.find_link, b'<a href="https://evil.example/62020001.xlsx">x</a>', ur.LATEST_URL, ur.SHEET_ENDING)


def test_parse_spreadsheet_fixture_picks_the_right_column():
    v = a.parse_spreadsheet_series(XLSX, ur.SHEET_ID, expected_meta=ur.SHEET_META)
    assert len(v) == 10 and min(v) == "2019-11" and max(v) == "2020-08"
    assert 5.0 < float(v["2019-12"]) < 5.1   # the unemployment rate, not the 12,000 thousand employed


def test_spreadsheet_refuses_wrong_series_or_metadata():
    rows = sheet_rows()
    raises(a.parse_spreadsheet_series, make_sheet(rows, sid="A99999999X"), ur.SHEET_ID, expected_meta=ur.SHEET_META)
    assert "description" in raises(a.parse_spreadsheet_series, make_sheet(rows, description="Employed total ; Persons ;"), ur.SHEET_ID, expected_meta=ur.SHEET_META)
    assert "Series Type" in raises(a.parse_spreadsheet_series, make_sheet(rows, series_type="Trend"), ur.SHEET_ID, expected_meta=ur.SHEET_META)
    assert "Unit" in raises(a.parse_spreadsheet_series, make_sheet(rows, unit="000"), ur.SHEET_ID, expected_meta=ur.SHEET_META)


def test_spreadsheet_refuses_duplicate_missing_and_bad_rows():
    rows = sheet_rows()
    assert "appears twice" in raises(a.parse_spreadsheet_series, make_sheet(rows + [rows[2]]), ur.SHEET_ID)
    assert "missing months" in raises(a.parse_spreadsheet_series, make_sheet(rows[:3] + rows[4:]), ur.SHEET_ID)
    bad = [list(r) for r in rows]
    bad[2][1] = "n/a"
    assert "unreadable value" in raises(a.parse_spreadsheet_series, make_sheet([tuple(r) for r in bad]), ur.SHEET_ID)
    bad[2] = [datetime(2020, 1, 15), 5.0]
    assert "first day of a month" in raises(a.parse_spreadsheet_series, make_sheet([tuple(r) for r in bad]), ur.SHEET_ID)
    raises(a.parse_spreadsheet_series, b"not an excel file", ur.SHEET_ID)


# ---------------------------------------------------------------- the cross-check

def test_cross_check_agrees_on_the_fixtures():
    s = a.parse_sdmx_series(API, ur.EXPECTED)
    v = a.parse_spreadsheet_series(XLSX, ur.SHEET_ID)
    assert a.cross_check(s, v, quiet) == (10, "2019-11", "2020-08")


def test_cross_check_refuses_a_disagreeing_month():
    rows = sheet_rows()
    rows[3] = (rows[3][0], rows[3][1] + 0.2)
    s = a.parse_sdmx_series(API, ur.EXPECTED)
    msg = raises(a.cross_check, s, a.parse_spreadsheet_series(make_sheet(rows), ur.SHEET_ID), quiet)
    assert "disagree in 1 month" in msg and rows[3][0].strftime("%Y-%m") in msg


def test_cross_check_refuses_a_different_latest_month():
    rows = sheet_rows()
    s = a.parse_sdmx_series(API, ur.EXPECTED)
    msg = raises(a.cross_check, s, a.parse_spreadsheet_series(make_sheet(rows[:-1]), ur.SHEET_ID), quiet)
    assert "latest month differs" in msg and "2020-08" in msg and "2020-07" in msg
    rows2 = rows + [(datetime(2020, 9, 1), 6.9)]
    raises(a.cross_check, s, a.parse_spreadsheet_series(make_sheet(rows2), ur.SHEET_ID), quiet)


def test_cross_check_refuses_a_spreadsheet_with_a_missing_month():
    rows = sheet_rows()
    raises(a.parse_spreadsheet_series, make_sheet(rows[:4] + rows[5:]), ur.SHEET_ID)


def test_small_float_noise_in_the_spreadsheet_does_not_cause_a_false_alarm():
    # The sheet has 7 decimals, the API 8; both round to the same single decimal.
    s = a.parse_sdmx_series(API, ur.EXPECTED)
    v = a.parse_spreadsheet_series(XLSX, ur.SHEET_ID)
    assert a.cross_check(s, v, quiet)[0] == 10


# ---------------------------------------------------------------- the whole scraper

def run_in(root, **kw):
    return ur.run(root=root, fetcher=kw.get("fetcher") or fake_fetcher(), log=quiet)


def test_run_writes_data_sources_and_manifest_and_is_repeatable():
    with tempfile.TemporaryDirectory() as t:
        calls = []
        run_in(t, fetcher=fake_fetcher(calls=calls))
        assert calls == [ur.API_URL, ur.LATEST_URL, SHEET_URL]
        d = Path(t) / "metrics" / "unemployment-rate"
        csv1 = (d / "data.csv").read_bytes()
        lines = csv1.decode().split("\n")
        assert lines[0] == "date,period,series,jurisdiction,value,unit,status"
        assert lines[1] == "2019-11-30,2019-11,unemployment_rate,Australia,5.2,pct,actual"
        assert lines[3].startswith("2020-01-31,") and lines[4].startswith("2020-02-29,")  # leap day
        assert lines[-2].startswith("2020-08-31,") and lines[-1] == ""
        assert len(lines) == 12
        # raw files byte for byte, manifest accurate
        assert (d / "sources" / ur.API_NAME).read_bytes() == API
        assert (d / "sources" / ur.SHEET_NAME).read_bytes() == XLSX
        m = json.loads((d / "sources" / "manifest.json").read_text())
        assert m[ur.SHEET_NAME]["url"] == SHEET_URL and m[ur.SHEET_NAME]["bytes"] == len(XLSX)
        assert m[ur.API_NAME]["url"] == ur.API_URL and len(m[ur.API_NAME]["sha256"]) == 64
        # same figures, rows delivered in another order: identical data.csv
        lines_in = API.decode().splitlines()
        reordered = ("\n".join([lines_in[0]] + lines_in[1:][::-1]) + "\n").encode()
        run_in(t, fetcher=fake_fetcher(api=reordered))
        assert (d / "data.csv").read_bytes() == csv1


def test_run_writes_nothing_when_the_cross_check_fails():
    rows = sheet_rows()
    rows[5] = (rows[5][0], rows[5][1] + 0.5)
    with tempfile.TemporaryDirectory() as t:
        raises(ur.run, root=t, fetcher=fake_fetcher(xlsx=make_sheet(rows)), log=quiet)
        assert not (Path(t) / "metrics").exists()


def test_run_writes_nothing_when_the_api_is_wrong():
    with tempfile.TemporaryDirectory() as t:
        raises(ur.run, root=t, fetcher=fake_fetcher(api=api_without("2020-03")), log=quiet)
        raises(ur.run, root=t, fetcher=fake_fetcher(api=api_with(",M13,", ",M14,")), log=quiet)
        assert not (Path(t) / "metrics").exists()


def test_run_refuses_fewer_rows_than_before():
    with tempfile.TemporaryDirectory() as t:
        run_in(t)
        before = (Path(t) / "metrics" / "unemployment-rate" / "data.csv").read_bytes()
        rows = sheet_rows()[:-1]
        api = "\n".join(l for l in API.decode().splitlines() if ",2020-08," not in l) + "\n"
        f = fake_fetcher(api=api.encode(), xlsx=make_sheet(rows))
        assert "fewer than" in raises(ur.run, root=t, fetcher=f, log=quiet)
        assert (Path(t) / "metrics" / "unemployment-rate" / "data.csv").read_bytes() == before


def test_run_refuses_when_the_page_has_no_link():
    with tempfile.TemporaryDirectory() as t:
        raises(ur.run, root=t, fetcher=fake_fetcher(html=b"<html></html>"), log=quiet)


def test_main_exits_1_on_failure():
    orig = ur.run
    def boom(**kw):
        raise a.ScrapeError("test failure")
    ur.run = boom
    try:
        assert ur.main(["--root", "/nonexistent"]) == 1
    finally:
        ur.run = orig


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"pass {name}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
