#!/usr/bin/env python3
"""Tests for scrapers/wages_and_prices.py and the parts of scrapers/abs_series.py it uses for the first
time (leading blank values, no DECIMALS column, quarterly spreadsheet rows). Plain asserts, no pytest needed.

Run from the project folder:  python3 scrapers/tests/test_wages_and_prices.py

No network. Small trimmed copies of the real files are in fixtures/:
  abs-wpi-api-trimmed.csv               the ABS Wage Price Index response, 1997-Q3 to 1999-Q4: four blank quarters
                                        (OBS_STATUS u), then six figures; no DECIMALS column; 1999-Q4 is "3"
  abs-wpi-table1-trimmed.xlsx           Table 1 with the real header rows for two columns (a decoy index series and
                                        A83895396W), same quarters; the first four cells of A83895396W are empty
  abs-wpi-latest-release.html           the real 634501 .. 6345xx links
  inflation-data-for-wages-trimmed.csv  a few rows of the inflation page's data.csv: headline_quarterly 1997-Q4 to
                                        1999-Q4, and one row each of two other series that must be ignored
Variants for the refusal cases are made in the tests by editing those bytes or building a small workbook.
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
import wages_and_prices as wp  # noqa: E402
import openpyxl  # noqa: E402

FX = HERE / "fixtures"
API = (FX / "abs-wpi-api-trimmed.csv").read_bytes()
XLSX = (FX / "abs-wpi-table1-trimmed.xlsx").read_bytes()
HTML = (FX / "abs-wpi-latest-release.html").read_bytes()
INFLATION = (FX / "inflation-data-for-wages-trimmed.csv").read_bytes()
quiet = lambda msg: None  # noqa: E731
SHEET_URL = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia/sep-2026/634501.xlsx"
HEADER = wp.SHEET_META["description"]
# the wage figures in the fixture, by quarter
FIRST = "1998-Q3"
LAST = "1999-Q4"
QUARTERS = ["1998-Q3", "1998-Q4", "1999-Q1", "1999-Q2", "1999-Q3", "1999-Q4"]


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {getattr(fn, '__name__', fn)}")


def edit(raw, old, new, count=1):
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode()
    assert old in text, old
    return text.replace(old, new, count).encode()


def make_sheet(rows, header=HEADER, sid="A83895396W", series_type="Seasonally Adjusted", unit="Percent", extra_same_id=False):
    """A small workbook shaped like Table 1 (quarterly). rows is [(datetime, value or None)]."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data1"
    heads = [None, "Index Numbers ; Total hourly rates of pay excluding bonuses ;", header]
    ids = ["Series ID", "A2603039T", sid]
    if extra_same_id:
        heads.append(header)
        ids.append(sid)
    n = len(heads) - 1
    ws.append(heads)
    ws.append(["Unit", "Index Numbers", unit] + ["Percent"] * (n - 2))
    ws.append(["Series Type", "Original", series_type] + ["Original"] * (n - 2))
    ws.append(["Data Type", "INDEX", "PERCENT"] + ["PERCENT"] * (n - 2))
    ws.append(["Frequency", "Quarter", "Quarter"] + ["Quarter"] * (n - 2))
    ws.append(["Collection Month", 3, 3] + [3] * (n - 2))
    ws.append(["Series Start", rows[0][0], rows[0][0]] + [rows[0][0]] * (n - 2))
    ws.append(["Series End", rows[-1][0], rows[-1][0]] + [rows[-1][0]] * (n - 2))
    ws.append(["No. Obs", len(rows), len(rows)] + [len(rows)] * (n - 2))
    ws.append(ids)
    for d, v in rows:
        ws.append([d, 67.4, v] + [v] * (n - 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sheet_rows():
    """The fixture's own rows, as [(datetime, value)] (the first four values are None)."""
    wb = openpyxl.load_workbook(io.BytesIO(XLSX), data_only=True)
    return [(r[0], r[2]) for r in wb["Data1"].iter_rows(min_row=11, values_only=True)]


def api_with(old, new, count=1):
    return edit(API, old, new, count)


def inflation_without(period_or_series, only_series="headline_quarterly"):
    lines = INFLATION.decode().splitlines()
    kept = [l for l in lines if not (f",{period_or_series}," in l and f",{only_series}," in l)]
    assert len(kept) < len(lines), period_or_series
    return ("\n".join(kept) + "\n").encode()


def fake_fetcher(api=API, html=HTML, xlsx=XLSX, calls=None):
    def f(url, accept="*/*"):
        if calls is not None:
            calls.append(url)
        table = {wp.API_URL: api, wp.LATEST_URL: html, SHEET_URL: xlsx}
        if url not in table:
            raise AssertionError(f"unexpected download {url}")
        v = table[url]
        if isinstance(v, Exception):
            raise v
        return v
    return f


def make_root(t, inflation=INFLATION):
    """A project folder holding only the inflation page's data.csv (None: no such file)."""
    if inflation is not None:
        d = Path(t) / "metrics" / "inflation"
        d.mkdir(parents=True)
        (d / "data.csv").write_bytes(inflation)
    return t


# ---------------------------------------------------------------- the API response (abs_series.py)

def test_leading_blanks_are_skipped_and_the_figures_kept():
    s = a.parse_sdmx_series(API, wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)
    assert [p for p, _ in s.pairs] == QUARTERS
    assert s.skipped == ("1997-Q3", "1997-Q4", "1998-Q1", "1998-Q2")
    d = dict(s.pairs)
    assert d["1998-Q3"] == "3.3" and d["1999-Q3"] == "3.1"
    assert d["1999-Q4"] == "3.0"                      # the API's "3" is written with one decimal, nothing rounded
    assert s.decimals["1999-Q4"] == 1 and s.raw_values["1999-Q4"] == "3"


def test_blanks_are_refused_unless_skipping_is_asked_for_and_the_decimals_column_may_be_absent():
    # the default behaviour is unchanged: a blank value is unreadable
    assert "unreadable value" in raises(a.parse_sdmx_series, API, wp.EXPECTED, freq="Q", blank_decimals=1)
    # without blank_decimals the missing DECIMALS column is still refused (the Labour Force rule)
    assert "DECIMALS" in raises(a.parse_sdmx_series, API, wp.EXPECTED, freq="Q", skip_leading_blank=True)
    # a series with no blanks reports nothing skipped
    s = a.parse_sdmx_series(edit(API, "\r\n".join(l for l in API.decode().split("\r\n") if ",u," in l) + "\r\n", ""),
                            wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)
    assert s.skipped == () and len(s.pairs) == 6


def test_a_blank_after_the_first_figure_is_a_gap_and_is_refused():
    msg = raises(a.parse_sdmx_series, api_with(",1999-Q1,3.1,", ",1999-Q1,,"), wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)
    assert "blank value(s) for 1999-Q1" in msg and "after the first figure (1998-Q3)" in msg and "a gap" in msg, msg
    # a blank at the very end is a gap too (the latest quarter would otherwise be silently dropped)
    msg = raises(a.parse_sdmx_series, api_with(",1999-Q4,3,", ",1999-Q4,,"), wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)
    assert "1999-Q4" in msg and "a gap" in msg, msg
    # a blank in the middle of the leading run does not matter, but one more blank after it does
    msg = raises(a.parse_sdmx_series, api_with(",1998-Q4,3.1,", ",1998-Q4,,"), wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)
    assert "1998-Q4" in msg
    # every value blank: nothing to keep
    ls = API.decode().splitlines()
    all_blank = [ls[0]] + [",".join(l.split(",")[:9] + [""] + l.split(",")[10:]) for l in ls[1:]]
    assert "every value is blank" in raises(a.parse_sdmx_series, ("\r\n".join(all_blank) + "\r\n").encode(), wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)


def test_api_refusals():
    kw = dict(freq="Q", blank_decimals=1, skip_leading_blank=True)
    assert "2 decimal places" in raises(a.parse_sdmx_series, api_with(",1999-Q1,3.1,", ",1999-Q1,3.14,"), wp.EXPECTED, **kw)
    assert "nothing is rounded" in raises(a.parse_sdmx_series, api_with(",1999-Q1,3.1,", ",1999-Q1,3.14,"), wp.EXPECTED, **kw)
    assert "unreadable value" in raises(a.parse_sdmx_series, api_with(",1999-Q1,3.1,", ",1999-Q1,abc,"), wp.EXPECTED, **kw)
    assert "missing quarters 1999-Q1" in raises(a.parse_sdmx_series, edit(API, "ABS:WPI(1.2.0),3,THRPEB,7,TOT,20,AUS,Q,1999-Q1,3.1,PCT,,,\r\n", ""), wp.EXPECTED, **kw)
    assert "appears twice" in raises(a.parse_sdmx_series, API + b"ABS:WPI(1.2.0),3,THRPEB,7,TOT,20,AUS,Q,1999-Q2,3.1,PCT,,,\r\n", wp.EXPECTED, **kw)
    assert "unexpected period" in raises(a.parse_sdmx_series, api_with(",1999-Q1,", ",1999-Q5,"), wp.EXPECTED, **kw)
    assert "unexpected period" in raises(a.parse_sdmx_series, api_with(",1999-Q1,", ",1999-03,"), wp.EXPECTED, **kw)
    for col, old, new in (("MEASURE", ",3,THRPEB,", ",1,THRPEB,"), ("INDEX", ",THRPEB,", ",THRPEC,"), ("SECTOR", ",THRPEB,7,", ",THRPEB,1,"),
                          ("INDUSTRY", ",7,TOT,", ",7,A,"), ("TSEST", ",TOT,20,", ",TOT,10,"), ("REGION", ",20,AUS,", ",20,1,"),
                          ("FREQ", ",AUS,Q,", ",AUS,M,"), ("UNIT_MEASURE", ",PCT,", ",IN,")):
        msg = raises(a.parse_sdmx_series, edit(API, old, new, count=10), wp.EXPECTED, **kw)
        assert col in msg and "not the series asked for" in msg, msg


# ---------------------------------------------------------------- the spreadsheet

def test_quarterly_spreadsheet_column_is_read_by_series_id_and_checked():
    v = a.parse_spreadsheet_series(XLSX, wp.SHEET_ID, expected_meta=wp.SHEET_META, freq="Q")
    assert sorted(v) == QUARTERS and v["1998-Q3"] == "3.3" and v["1999-Q4"] == "3"     # the first four empty cells are left out; the number is read as the file holds it
    # whitespace in the header does not matter (the real file has doubled spaces)
    assert sorted(a.parse_spreadsheet_series(make_sheet(sheet_rows(), header=HEADER.replace(" ; ", " ;  ")), wp.SHEET_ID, expected_meta=wp.SHEET_META, freq="Q")) == QUARTERS


def test_quarterly_spreadsheet_refusals():
    rows = sheet_rows()
    kw = dict(expected_meta=wp.SHEET_META, freq="Q")
    assert "has Series Type 'Original'" in raises(a.parse_spreadsheet_series, make_sheet(rows, series_type="Original"), wp.SHEET_ID, **kw)
    assert "not the series asked for" in raises(a.parse_spreadsheet_series, make_sheet(rows, header=HEADER.replace("Private and Public", "Private")), wp.SHEET_ID, **kw)
    assert "not the series asked for" in raises(a.parse_spreadsheet_series, make_sheet(rows, unit="Index Numbers"), wp.SHEET_ID, **kw)
    assert "appears 0 times" in raises(a.parse_spreadsheet_series, make_sheet(rows, sid="A99999999X"), wp.SHEET_ID, **kw)
    assert "appears 2 times" in raises(a.parse_spreadsheet_series, make_sheet(rows, extra_same_id=True), wp.SHEET_ID, **kw)
    assert "no sheet 'Data2'" in raises(a.parse_spreadsheet_series, XLSX, wp.SHEET_ID, sheet="Data2", **kw)
    assert "could not be opened" in raises(a.parse_spreadsheet_series, b"not a spreadsheet", wp.SHEET_ID, **kw)
    bad_month = [(datetime(d.year, 11 if d.month == 12 and d.year == 1998 else d.month, 1), v) for d, v in rows]
    assert "not the first day of the last month of a quarter" in raises(a.parse_spreadsheet_series, make_sheet(bad_month), wp.SHEET_ID, **kw)
    assert "holds no values" in raises(a.parse_spreadsheet_series, make_sheet(rows[:4]), wp.SHEET_ID, **kw)
    without = [r for r in rows if r[0] != datetime(1999, 3, 1)]
    assert "missing quarters 1999-Q1" in raises(a.parse_spreadsheet_series, make_sheet(without), wp.SHEET_ID, **kw)
    assert "unknown frequency" in raises(a.parse_spreadsheet_series, XLSX, wp.SHEET_ID, freq="X")
    # asked for months (the default), a quarterly sheet is refused rather than misread
    assert "missing months" in raises(a.parse_spreadsheet_series, XLSX, wp.SHEET_ID)


def test_cross_check_agrees_and_refuses_each_kind_of_disagreement():
    series = a.parse_sdmx_series(API, wp.EXPECTED, freq="Q", blank_decimals=1, skip_leading_blank=True)
    sheet = a.parse_spreadsheet_series(XLSX, wp.SHEET_ID, expected_meta=wp.SHEET_META, freq="Q")
    msgs = []
    assert a.cross_check(series, sheet, msgs.append, noun="quarter") == (6, "1998-Q3", "1999-Q4")
    assert "6 quarters agree (1998-Q3 to 1999-Q4); the latest quarter is 1999-Q4 in both." in msgs[0]
    # one quarter differs by a tenth
    off = dict(sheet, **{"1999-Q1": "3.2"})
    msg = raises(a.cross_check, series, off, quiet, noun="quarter")
    assert "disagree in 1 quarter(s)" in msg and "1999-Q1: API 3.1" in msg, msg
    # the latest quarter differs
    assert "latest quarter differs" in raises(a.cross_check, series, {k: v for k, v in sheet.items() if k != "1999-Q4"}, quiet, noun="quarter")


# ---------------------------------------------------------------- the inflation page's figures

def test_read_inflation_copies_the_quarters_from_the_first_wage_quarter_and_ignores_other_series():
    with tempfile.TemporaryDirectory() as t:
        make_root(t)
        pairs, sha, n = wp.read_inflation(t, FIRST, LAST, quiet)
        assert [p for p, _ in pairs] == QUARTERS
        assert dict(pairs) == {"1998-Q3": "1.4", "1998-Q4": "1.6", "1999-Q1": "1.2", "1999-Q2": "1.1", "1999-Q3": "1.7", "1999-Q4": "1.8"}
        import hashlib
        assert sha == hashlib.sha256(INFLATION).hexdigest() and n == len(INFLATION)
        # a later last quarter on the inflation side (prices run ahead of wages) is fine
        later = INFLATION + b"2000-03-31,2000-Q1,headline_quarterly,Australia,2.0,pct,actual\n"
        make_root(t + "/b", later)
        assert wp.read_inflation(t + "/b", FIRST, LAST, quiet)[0][-1] == ("2000-Q1", "2.0")


def test_read_inflation_refuses_a_missing_file_a_gap_and_other_problems():
    with tempfile.TemporaryDirectory() as t:
        assert "is missing" in raises(wp.read_inflation, t, FIRST, LAST, quiet)
        assert "must run before this one" in raises(wp.read_inflation, t, FIRST, LAST, quiet)
    def with_inflation(raw, first=FIRST, last=LAST):
        with tempfile.TemporaryDirectory() as t:
            make_root(t, raw)
            return raises(wp.read_inflation, t, first, last, quiet)
    assert "missing quarters 1999-Q1" in with_inflation(inflation_without("1999-Q1"))
    assert "no headline_quarterly figure for 1998-Q3" in with_inflation(inflation_without("1998-Q3"))
    assert "ends at 1999-Q3, before the latest wage quarter 1999-Q4" in with_inflation(inflation_without("1999-Q4"))
    # a gap before the first wage quarter is outside the range and does not matter
    with tempfile.TemporaryDirectory() as t:
        make_root(t, inflation_without("1998-Q1"))
        assert len(wp.read_inflation(t, FIRST, LAST, quiet)[0]) == 6
    assert "has no headline_quarterly rows" in with_inflation(INFLATION.replace(b",headline_quarterly,", b",headline_other,"))
    assert "more than one decimal place" in with_inflation(INFLATION.replace(b",1.2,pct", b",1.25,pct"))
    assert "unreadable value" in with_inflation(INFLATION.replace(b",1.2,pct", b",n/a,pct"))
    assert "twice" in with_inflation(INFLATION + b"1999-03-31,1999-Q1,headline_quarterly,Australia,1.2,pct,actual\n")
    assert "a quarter label and its last day" in with_inflation(INFLATION.replace(b"1999-03-31,1999-Q1", b"1999-03-30,1999-Q1"))
    assert "does not have the header" in with_inflation(INFLATION.replace(b"date,period", b"day,period"))
    assert "has 3 fields; expected 7" in with_inflation(INFLATION + b"1999-06-30,1999-Q2,headline_quarterly\n")
    assert "not text" in with_inflation(b"\xff\xfe\x00")


# ---------------------------------------------------------------- the whole run

def run_in(root, **kw):
    return wp.run(root=root, fetcher=kw.get("fetcher") or fake_fetcher(), log=quiet)


def test_run_writes_data_sources_and_manifest_and_is_repeatable():
    with tempfile.TemporaryDirectory() as t:
        make_root(t)
        calls = []
        res = run_in(t, fetcher=fake_fetcher(calls=calls))
        assert calls == [wp.API_URL, wp.LATEST_URL, SHEET_URL]       # nothing is downloaded for price growth
        d = Path(t) / "metrics" / "wages-and-prices"
        csv1 = (d / "data.csv").read_bytes()
        lines = csv1.decode().split("\n")
        assert lines[0] == "date,period,series,jurisdiction,value,unit,status" and lines[-1] == ""
        assert len(lines) == 1 + 6 + 6 + 1
        assert lines[1] == "1998-09-30,1998-Q3,price_growth,Australia,1.4,pct,actual"
        assert lines[7] == "1998-09-30,1998-Q3,wage_growth,Australia,3.3,pct,actual"
        assert lines[12] == "1999-12-31,1999-Q4,wage_growth,Australia,3.0,pct,actual"
        body = lines[1:-1]
        assert body == sorted(body, key=lambda l: (l.split(",")[2], l.split(",")[0]))
        assert res["check"] == (6, "1998-Q3", "1999-Q4") and res["sheet_id"] == "A83895396W"
        # raw files byte for byte; the manifest is accurate and holds the reference to the inflation file
        m = json.loads((d / "sources" / "manifest.json").read_text())
        assert sorted(m) == sorted([wp.API_NAME, wp.SHEET_NAME, wp.INFLATION_MANIFEST_KEY])
        for name, raw in ((wp.API_NAME, API), (wp.SHEET_NAME, XLSX)):
            assert (d / "sources" / name).read_bytes() == raw
            assert m[name]["bytes"] == len(raw) and len(m[name]["sha256"]) == 64
        assert m[wp.SHEET_NAME]["url"] == SHEET_URL and m[wp.API_NAME]["url"] == wp.API_URL
        ref = m[wp.INFLATION_MANIFEST_KEY]
        assert ref["path"] == "metrics/inflation/data.csv" and ref["series"] == "headline_quarterly"
        assert ref["sha256"] == res["inflation_sha256"] and ref["bytes"] == len(INFLATION)
        assert sorted(p.name for p in (d / "sources").iterdir()) == sorted([wp.API_NAME, wp.SHEET_NAME, "manifest.json"])   # no copy of the inflation file
        # a second run: identical data.csv; and the API rows in another order give the same figures
        run_in(t)
        assert (d / "data.csv").read_bytes() == csv1
        ls = API.decode().splitlines()
        run_in(t, fetcher=fake_fetcher(api=("\r\n".join([ls[0]] + ls[1:][::-1]) + "\r\n").encode()))
        assert (d / "data.csv").read_bytes() == csv1


def refuses_and_writes_nothing(inflation=INFLATION, **kw):
    with tempfile.TemporaryDirectory() as t:
        make_root(t, inflation)
        msg = raises(wp.run, root=t, fetcher=fake_fetcher(**kw), log=quiet)
        assert not (Path(t) / "metrics" / "wages-and-prices").exists(), "files were written although a check failed"
        return msg


def test_run_refuses_a_spreadsheet_that_disagrees():
    rows = sheet_rows()
    rows[7] = (rows[7][0], rows[7][1] + 0.1)                         # 1999-Q2
    msg = refuses_and_writes_nothing(xlsx=make_sheet(rows))
    assert "disagree in 1 quarter(s)" in msg and "1999-Q2" in msg, msg
    # the spreadsheet ends a quarter earlier or later than the API
    assert "cover different quarters" in refuses_and_writes_nothing(xlsx=make_sheet(rows[:-1]))
    assert "cover different quarters" in refuses_and_writes_nothing(xlsx=make_sheet(sheet_rows() + [(datetime(2000, 3, 1), 3.0)]))
    # a quarter missing from the middle of the API response
    assert "missing quarters 1999-Q1" in refuses_and_writes_nothing(api=edit(API, "ABS:WPI(1.2.0),3,THRPEB,7,TOT,20,AUS,Q,1999-Q1,3.1,PCT,,,\r\n", ""))
    # the wrong spreadsheet column
    assert "not the series asked for" in refuses_and_writes_nothing(xlsx=make_sheet(sheet_rows(), series_type="Original"))
    assert "no link ending in /634501.xlsx" in refuses_and_writes_nothing(html=b"<html><a href='/x/634502a.xlsx'>x</a></html>")


def test_run_refuses_a_blank_after_the_first_figure_and_bad_downloads():
    assert "a gap" in refuses_and_writes_nothing(api=api_with(",1999-Q1,3.1,", ",1999-Q1,,"))
    assert "HTTP 503" in refuses_and_writes_nothing(api=a.ScrapeError("https://x answered HTTP 503"))
    assert "2 decimal places" in refuses_and_writes_nothing(api=api_with(",1999-Q1,3.1,", ",1999-Q1,3.12,"))
    assert "not the series asked for" in refuses_and_writes_nothing(api=edit(API, ",THRPEB,7,", ",THRPEB,1,", count=10))
    assert "HTTP 404" in refuses_and_writes_nothing(xlsx=a.ScrapeError("https://x answered HTTP 404"))


def test_run_refuses_when_the_inflation_file_is_missing_or_has_a_gap():
    msg = refuses_and_writes_nothing(inflation=None)
    assert "is missing" in msg and "inflation scraper must run before" in msg, msg
    assert "missing quarters 1999-Q1" in refuses_and_writes_nothing(inflation=inflation_without("1999-Q1"))
    assert "before the latest wage quarter" in refuses_and_writes_nothing(inflation=inflation_without("1999-Q4"))
    assert "no headline_quarterly figure for 1998-Q3" in refuses_and_writes_nothing(inflation=inflation_without("1998-Q3"))


def test_run_refuses_fewer_rows_than_before_for_each_series():
    for series in ("wage_growth", "price_growth"):
        with tempfile.TemporaryDirectory() as t:
            make_root(t)
            run_in(t)
            path = Path(t) / "metrics" / "wages-and-prices" / "data.csv"
            path.write_text(path.read_text() + f"2000-03-31,2000-Q1,{series},Australia,3.0,pct,actual\n")
            before = path.read_bytes()
            msg = raises(wp.run, root=t, fetcher=fake_fetcher(), log=quiet)
            assert "fewer than the 7 already in data.csv" in msg, msg
            assert path.read_bytes() == before


def test_run_refuses_a_series_that_starts_later_than_before():
    with tempfile.TemporaryDirectory() as t:
        make_root(t)
        run_in(t)
        path = Path(t) / "metrics" / "wages-and-prices" / "data.csv"
        # an earlier run held six price quarters starting a year before the wage series
        lines = path.read_text().splitlines()
        kept = [l for l in lines if ",price_growth," not in l]
        early = [f"{y}-{m}-{d},{y}-Q{q},price_growth,Australia,0.0,pct,actual" for y, m, d, q in
                 ((1997, "03", 31, 1), (1997, "06", 30, 2), (1997, "09", 30, 3), (1997, "12", 31, 4), (1998, "03", 31, 1), (1998, "06", 30, 2))]
        path.write_text("\n".join(kept + early) + "\n")
        assert "now starts at 1998-Q3, later than the 1997-Q1" in raises(wp.run, root=t, fetcher=fake_fetcher(), log=quiet)


def test_one_decimal_never_rounds():
    assert wp.one_decimal("3", "x") == "3.0" and wp.one_decimal("-0.3", "x") == "-0.3" and wp.one_decimal("3.5", "x") == "3.5"
    assert "more than one decimal place" in raises(wp.one_decimal, "3.55", "the figure")


def test_main_exits_1_on_failure():
    orig = wp.run

    def boom(**kw):
        raise a.ScrapeError("test failure")
    wp.run = boom
    try:
        assert wp.main(["--root", "/nonexistent"]) == 1
    finally:
        wp.run = orig


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
