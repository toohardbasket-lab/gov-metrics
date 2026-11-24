#!/usr/bin/env python3
"""Tests for scrapers/rents.py and the parts of scrapers/abs_series.py it uses for the first time (a header
that only has to contain some text, several sheets, several columns with one header). Plain asserts, no
pytest needed (pytest also finds them).

Run from the project folder:  python3 scrapers/tests/test_rents.py

No network. Small trimmed copies of the real files are in fixtures/ (made from the 24 November 2026 downloads):
  abs-rents-index-api-trimmed.csv         the rents index, 1972-Q3 to 1974-Q4 (10 quarters, two decimals)
  abs-rents-monthly-api-trimmed.csv       the national twelve-month change, July to September 2025
  abs-rents-cities-api-trimmed.csv        the same for REGION 1 to 8, in the order the ABS sent them
  abs-rents-cities-labels-trimmed.csv     the cities response asked for with labels ("2: Melbourne")
  abs-rents-table18-trimmed.xlsx          Table 18: the real header rows, series A2331876F and a column with the
                                          same header and another series ID (A2326431V), same quarters
  abs-rents-table3-trimmed.xlsx           Table 3: A130390095C and the second column with the same header
  abs-rents-table11-trimmed.xlsx          Table 11: sheets Data1 to Data4 with two Original columns per city
  abs-rents-latest-release.html           the real 6401018, 640103 and 6401011 links
Variants for the refusal cases are made in the tests by editing those bytes or workbooks.
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
import rents as r  # noqa: E402
import openpyxl  # noqa: E402

FX = HERE / "fixtures"
INDEX = (FX / "abs-rents-index-api-trimmed.csv").read_bytes()
MONTHLY = (FX / "abs-rents-monthly-api-trimmed.csv").read_bytes()
CITIES = (FX / "abs-rents-cities-api-trimmed.csv").read_bytes()
LABELS = (FX / "abs-rents-cities-labels-trimmed.csv").read_bytes()
T18 = (FX / "abs-rents-table18-trimmed.xlsx").read_bytes()
T3 = (FX / "abs-rents-table3-trimmed.xlsx").read_bytes()
T11 = (FX / "abs-rents-table11-trimmed.xlsx").read_bytes()
HTML = (FX / "abs-rents-latest-release.html").read_bytes()
quiet = lambda msg: None  # noqa: E731
BASE = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/sep-2026/"
URL18, URL3, URL11 = BASE + "6401018.xlsx", BASE + "640103.xlsx", BASE + "6401011.xlsx"
QUARTERS = ["1972-Q3", "1972-Q4", "1973-Q1", "1973-Q2", "1973-Q3", "1973-Q4", "1974-Q1", "1974-Q2", "1974-Q3", "1974-Q4"]
MONTHS = ["2025-07", "2025-08", "2025-09"]


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {getattr(fn, '__name__', fn)}")


def edit(raw, old, new, count=1):
    text = raw.decode()
    assert old in text, old
    return text.replace(old, new, count).encode()


def without_lines(raw, needle):
    lines = raw.decode().splitlines()
    kept = [l for l in lines if needle not in l]
    assert len(kept) < len(lines), needle
    return ("\n".join(kept) + "\n").encode()


def edit_xlsx(raw, fn):
    """Opens a workbook, lets fn(workbook) change it, and returns the new bytes."""
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    fn(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def column_of(ws, series_id):
    """The column number (1-based) whose Series ID row holds series_id."""
    for row in ws.iter_rows(min_row=10, max_row=10):
        for c in row:
            if c.value == series_id:
                return c.column
    raise AssertionError(series_id)


def row_of(ws, year, month):
    for row in ws.iter_rows(min_row=11):
        if isinstance(row[0].value, datetime) and (row[0].value.year, row[0].value.month) == (year, month):
            return row[0].row
    raise AssertionError((year, month))


def change_cell(sheet, series_id, year, month, value):
    def fn(wb):
        ws = wb[sheet]
        ws.cell(row_of(ws, year, month), column_of(ws, series_id)).value = value
    return fn


def delete_row(sheet, year, month):
    def fn(wb):
        ws = wb[sheet]
        ws.delete_rows(row_of(ws, year, month))
    return fn


def fake_fetcher(index=INDEX, monthly=MONTHLY, cities=CITIES, labels=LABELS, html=HTML, t18=T18, t3=T3, t11=T11, calls=None):
    def f(url, accept="*/*"):
        if calls is not None:
            calls.append((url, accept))
        if url == r.CITIES_URL:
            v = labels if accept == r.ACCEPT_LABELS else cities
        else:
            table = {r.INDEX_URL: index, r.MONTHLY_URL: monthly, r.LATEST_URL: html, URL18: t18, URL3: t3, URL11: t11}
            if url not in table:
                raise AssertionError(f"unexpected download {url}")
            v = table[url]
        if isinstance(v, Exception):
            raise v
        return v
    return f


def run_in(root, **kw):
    return r.run(root=root, fetcher=fake_fetcher(**kw), log=quiet)


# ---------------------------------------------------------------- the index and the monthly figures

def test_index_is_read_with_up_to_two_decimals_and_never_rounded():
    s = a.parse_sdmx_series(INDEX, r.EXPECTED_INDEX, freq="Q", blank_decimals=r.INDEX_DECIMALS)
    assert [p for p, _ in s.pairs] == QUARTERS
    d = dict(s.pairs)
    assert d["1972-Q3"] == "7.07" and d["1973-Q2"] == "7.40"  # "7.4" is written with two places
    bad = edit(INDEX, "7.07", "7.075")
    assert "3 decimal places" in raises(a.parse_sdmx_series, bad, r.EXPECTED_INDEX, freq="Q", blank_decimals=r.INDEX_DECIMALS)


def test_index_refusals():
    ex = r.EXPECTED_INDEX
    assert "not the series asked for" in raises(a.parse_sdmx_series, edit(INDEX, ",115522,", ",10001,"), ex, freq="Q", blank_decimals=2)
    assert "missing quarters 1973-Q1" in raises(a.parse_sdmx_series, without_lines(INDEX, "1973-Q1"), ex, freq="Q", blank_decimals=2)
    assert "appears twice" in raises(a.parse_sdmx_series, edit(INDEX, "1973-Q2", "1973-Q1"), ex, freq="Q", blank_decimals=2)


def test_monthly_is_read_with_one_decimal():
    s = a.parse_sdmx_series(MONTHLY, r.EXPECTED_MONTHLY, freq="M", blank_decimals=1)
    assert s.pairs == [("2025-07", "3.9"), ("2025-08", "3.7"), ("2025-09", "3.8")]
    assert "2 decimal places" in raises(a.parse_sdmx_series, edit(MONTHLY, ",3.7,", ",3.75,"), r.EXPECTED_MONTHLY, freq="M", blank_decimals=1)


# ---------------------------------------------------------------- the eight capitals

def test_cities_split_by_region_and_each_part_parses():
    parts = r.split_by_region(CITIES)
    assert sorted(parts) == ["1", "2", "3", "4", "5", "6", "7", "8"]
    for code, raw in parts.items():
        s = a.parse_sdmx_series(raw, dict(r.EXPECTED_MONTHLY, REGION=code), freq="M", blank_decimals=1)
        assert [p for p, _ in s.pairs] == MONTHS
    hobart = a.parse_sdmx_series(parts["6"], dict(r.EXPECTED_MONTHLY, REGION="6"), freq="M", blank_decimals=1)
    assert hobart.pairs == [("2025-07", "-0.7"), ("2025-08", "-0.6"), ("2025-09", "0.2")]


def test_cities_split_refuses_a_missing_or_extra_region():
    assert "expected exactly" in raises(r.split_by_region, without_lines(CITIES, ",8,M,"))
    extra = CITIES + b"ABS:CPI(2.0.0),3,115522,10,9,M,2025-07,1.0,PCT,,,,25\n"
    assert "expected exactly" in raises(r.split_by_region, extra)
    assert "lacks the column REGION" in raises(r.split_by_region, edit(CITIES, "REGION", "AREA"))


def test_region_names_are_confirmed():
    names = r.check_region_names(LABELS, CITIES)
    assert names == {"1": "Sydney", "2": "Melbourne", "3": "Brisbane", "4": "Adelaide", "5": "Perth", "6": "Hobart", "7": "Darwin", "8": "Canberra"}


def test_a_wrong_region_name_is_refused():
    msg = raises(r.check_region_names, edit(LABELS, "5: Perth", "5: Hobart", count=3), CITIES)
    assert "not named as expected" in msg and "5: 'Hobart' (expected 'Perth')" in msg
    # two cities swapped codes
    swapped = edit(LABELS, "1: Sydney", "1: @", count=100)
    swapped = edit(swapped, "2: Melbourne", "2: Sydney", count=100)
    swapped = edit(swapped, "1: @", "1: Melbourne", count=100)
    assert "not named as expected" in raises(r.check_region_names, swapped, CITIES)
    # a code with two names, a REGION column without names, an unexpected extra code
    assert "called both" in raises(r.check_region_names, edit(LABELS, "2: Melbourne", "2: Hobart"), CITIES)
    assert "does not carry names" in raises(r.check_region_names, edit(LABELS, "REGION: Region", "REGION"), CITIES)
    assert "do not hold the same figures" in raises(r.check_region_names, edit(LABELS, ",3.9,", ",3.8,"), CITIES)


def test_run_refuses_a_wrong_region_name_and_writes_nothing():
    with tempfile.TemporaryDirectory() as t:
        msg = raises(run_in, t, labels=edit(LABELS, "5: Perth", "5: Hobart", count=3))
        assert "not named as expected" in msg
        assert not (Path(t) / "metrics" / "rents").exists()


# ---------------------------------------------------------------- the spreadsheets

def test_headers_are_matched_by_text_in_every_data_sheet():
    got = a.find_series_ids_by_header(T11, ["Percentage Change from Corresponding Month of Previous Year ; Rents ; Perth ;"], series_type="Original")
    assert got == [("Data3", "A130392594J"), ("Data3", "A130395527L")]
    assert a.find_series_ids_by_header(T11, ["Rents ; Nowhere ;"], series_type="Original") == []
    # a series type that does not match leaves the column out
    assert a.find_series_ids_by_header(T11, ["Rents ; Perth ;"], series_type="Trend") == []


def test_header_contains_check():
    ok = a.parse_spreadsheet_series(T18, r.TABLE18_ID, freq="Q", expected_meta=r.TABLE18_META)
    assert sorted(ok) == QUARTERS and ok["1972-Q3"] == "7.07"
    meta = dict(r.TABLE18_META, description_contains="Index Numbers ; Rents ; Sydney ;")
    assert "does not contain" in raises(a.parse_spreadsheet_series, T18, r.TABLE18_ID, freq="Q", expected_meta=meta)


def test_table18_and_table3_cross_checks_agree():
    index = a.parse_sdmx_series(INDEX, r.EXPECTED_INDEX, freq="Q", blank_decimals=2)
    sheet = a.parse_spreadsheet_series(T18, r.TABLE18_ID, freq="Q", expected_meta=r.TABLE18_META)
    r.check_same_periods(index.pairs, sheet, "Table 18", "quarter")
    assert a.cross_check(index, sheet, quiet, noun="quarter") == (10, "1972-Q3", "1974-Q4")
    monthly = a.parse_sdmx_series(MONTHLY, r.EXPECTED_MONTHLY, freq="M", blank_decimals=1)
    sheet3 = a.parse_spreadsheet_series(T3, r.TABLE3_ID, freq="M", expected_meta=r.TABLE3_META)
    assert a.cross_check(monthly, sheet3, quiet, noun="month") == (3, "2025-07", "2025-09")


def city_series(code):
    part = r.split_by_region(CITIES)[code]
    return a.parse_sdmx_series(part, dict(r.EXPECTED_MONTHLY, REGION=code), freq="M", blank_decimals=1)


def test_every_city_agrees_with_both_table11_columns():
    for code, (city, _state) in r.REGIONS.items():
        ids, n, first, last = r.check_city(city, city_series(code), T11, quiet)
        assert len(ids) == 2 and ids[0] != ids[1] and (n, first, last) == (3, "2025-07", "2025-09"), city
    assert r.check_city("Sydney", city_series("1"), T11, quiet)[0] == ["A130392587K", "A130390459F"]


def test_a_city_that_disagrees_with_the_api_is_refused():
    # both spreadsheet columns say the same, but not what the API says
    bad = edit_xlsx(T11, lambda wb: (change_cell("Data1", "A130392587K", 2025, 8, 9.9)(wb), change_cell("Data1", "A130390459F", 2025, 8, 9.9)(wb)))
    msg = raises(r.check_city, "Sydney", city_series("1"), bad, quiet)
    assert "Sydney" in msg and "disagree" in msg and "2025-08" in msg
    # the API has a different figure from the sheet
    api = a.parse_sdmx_series(edit(r.split_by_region(CITIES)["1"], "2025-09,3.2", "2025-09,3.3"), dict(r.EXPECTED_MONTHLY, REGION="1"), freq="M", blank_decimals=1)
    assert "2025-09" in raises(r.check_city, "Sydney", api, T11, quiet)


def test_the_two_duplicate_columns_disagreeing_is_refused():
    bad = edit_xlsx(T11, change_cell("Data3", "A130395527L", 2025, 9, 6.4))  # Perth's second column only
    msg = raises(r.check_city, "Perth", city_series("5"), bad, quiet)
    assert "the two columns for Perth" in msg and "A130392594J" in msg and "A130395527L" in msg and "2025-09" in msg
    # the other cities are not affected
    assert r.check_city("Sydney", city_series("1"), bad, quiet)[1] == 3


def test_a_city_with_the_wrong_number_of_columns_is_refused():
    def drop_second_sydney(wb):
        ws = wb["Data1"]
        ws.delete_cols(column_of(ws, "A130390459F"))
    msg = raises(r.check_city, "Sydney", city_series("1"), edit_xlsx(T11, drop_second_sydney), quiet)
    assert "expected exactly 2" in msg
    # a column that is not Original is not counted
    def season(wb):
        ws = wb["Data1"]
        ws.cell(3, column_of(ws, "A130390459F")).value = "Seasonally Adjusted"
    assert "expected exactly 2" in raises(r.check_city, "Sydney", city_series("1"), edit_xlsx(T11, season), quiet)


def test_a_gap_in_a_spreadsheet_or_in_the_api_is_refused():
    gap_sheet = edit_xlsx(T11, lambda wb: [delete_row(s, 2025, 8)(wb) for s in ("Data1",)])
    assert "missing months" in raises(r.check_city, "Sydney", city_series("1"), gap_sheet, quiet)
    part = without_lines(r.split_by_region(CITIES)["1"], "2025-08")
    assert "missing months" in raises(a.parse_sdmx_series, part, dict(r.EXPECTED_MONTHLY, REGION="1"), freq="M", blank_decimals=1)
    gap_t18 = edit_xlsx(T18, delete_row("Data1", 1973, 3))
    assert "missing quarters" in raises(a.parse_spreadsheet_series, gap_t18, r.TABLE18_ID, freq="Q", expected_meta=r.TABLE18_META)


def test_the_cities_must_cover_the_same_months():
    with tempfile.TemporaryDirectory() as t:
        short = without_lines(without_lines(CITIES, ",5,M,2025-07,"), ",5,M,2025-08,")  # Perth has one month only
        short_labels = without_lines(without_lines(LABELS, "5: Perth,M: Monthly,2025-07"), "5: Perth,M: Monthly,2025-08")
        msg = raises(run_in, t, cities=short, labels=short_labels)
        assert "do not cover the same months" in msg


# ---------------------------------------------------------------- the worked-out change

def test_worked_out_change_from_the_fixture():
    s = a.parse_sdmx_series(INDEX, r.EXPECTED_INDEX, freq="Q", blank_decimals=2)
    w = r.worked_out_change(s.pairs)
    assert sorted(w) == QUARTERS[4:]  # the first figure is four quarters after the first index
    assert w["1973-Q3"] == ("6.8", "7.55", "7.07")  # 7.55 / 7.07 - 1 = 6.789 per cent
    assert w["1974-Q4"] == ("13.2", "8.83", "7.80")


def test_worked_out_change_rounds_half_up_and_is_exact():
    def one(a_, b_):
        pairs = [("2020-Q1", b_), ("2020-Q2", "1"), ("2020-Q3", "1"), ("2020-Q4", "1"), ("2021-Q1", a_)]
        return r.worked_out_change(pairs)["2021-Q1"][0]
    assert one("100.25", "100.00") == "0.3"   # exactly 0.25: up
    assert one("100.05", "100.00") == "0.1"   # exactly 0.05: up
    assert one("100.04", "100.00") == "0.0"
    assert one("99.75", "100.00") == "-0.3"   # a tie below zero goes away from zero, as ROUND_HALF_UP does
    assert one("99.97", "100.00") == "0.0"    # never "-0.0"
    assert one("105", "100") == "5.0"


def test_a_gap_makes_the_worked_out_figure_blank_not_wrong():
    s = a.parse_sdmx_series(INDEX, r.EXPECTED_INDEX, freq="Q", blank_decimals=2)
    pairs = [(p, v) for p, v in s.pairs if p != "1973-Q1"]
    w = r.worked_out_change(pairs)
    assert "1974-Q1" not in w and "1973-Q1" not in w   # 1974-Q1 needs 1973-Q1; 1973-Q1 has no index
    assert w["1974-Q2"][0] == "10.4" and w["1973-Q3"][0] == "6.8"  # the others are unaffected


# ---------------------------------------------------------------- run

def read_rows(root):
    return (Path(root) / "metrics" / "rents" / "data.csv").read_text(encoding="utf-8").splitlines()


def test_run_writes_data_sources_and_manifest_and_is_repeatable():
    with tempfile.TemporaryDirectory() as t:
        out = run_in(t)
        rows = read_rows(t)
        assert rows[0] == "date,period,series,jurisdiction,value,unit,status"
        assert len(rows) == 1 + 10 + 3 + 24
        assert rows[1] == "1972-09-30,1972-Q3,rents_index_quarterly,Australia,7.07,index,actual"
        assert "2025-09-30,2025-09,rents_monthly,Australia,3.8,pct,actual" in rows
        assert "2025-09-30,2025-09,rents_monthly,Western Australia,6.3,pct,actual" in rows
        assert "2025-07-31,2025-07,rents_monthly,Tasmania,-0.7,pct,actual" in rows
        assert "2025-09-30,2025-09,rents_monthly,Australian Capital Territory,0.7,pct,actual" in rows
        assert not any("rents_quarterly" in l for l in rows)  # the worked-out series is never stored
        jur = sorted({l.split(",")[3] for l in rows[1:] if ",rents_monthly," in l})
        assert jur == ["Australia", "Australian Capital Territory", "New South Wales", "Northern Territory", "Queensland",
                       "South Australia", "Tasmania", "Victoria", "Western Australia"]
        # sorted by series, jurisdiction, then date
        keys = [(l.split(",")[2], l.split(",")[3], l.split(",")[0]) for l in rows[1:]]
        assert keys == sorted(keys)
        names = {p.name for p in (Path(t) / "metrics" / "rents" / "sources").iterdir()}
        assert names == {r.INDEX_NAME, r.MONTHLY_NAME, r.CITIES_NAME, r.CITIES_LABELS_NAME, r.TABLE18_NAME, r.TABLE3_NAME, r.TABLE11_NAME, "manifest.json"}
        man = json.loads((Path(t) / "metrics" / "rents" / "sources" / "manifest.json").read_text())
        assert set(man) == names - {"manifest.json"}
        assert all(len(v["sha256"]) == 64 and v["bytes"] > 0 and v["url"].startswith("https://") for v in man.values())
        # saved byte for byte
        assert (Path(t) / "metrics" / "rents" / "sources" / r.TABLE11_NAME).read_bytes() == T11
        assert (Path(t) / "metrics" / "rents" / "sources" / r.CITIES_LABELS_NAME).read_bytes() == LABELS
        first = (Path(t) / "metrics" / "rents" / "data.csv").read_bytes()
        run_in(t)
        assert (Path(t) / "metrics" / "rents" / "data.csv").read_bytes() == first
        assert out["worked"]["1974-Q4"][0] == "13.2"
        assert out["index_check"] == (10, "1972-Q3", "1974-Q4") and out["monthly_check"] == (3, "2025-07", "2025-09")
        assert sorted(out["city_checks"]) == ["Adelaide", "Brisbane", "Canberra", "Darwin", "Hobart", "Melbourne", "Perth", "Sydney"]


def test_run_asks_for_the_labelled_response_from_the_same_address():
    calls = []
    with tempfile.TemporaryDirectory() as t:
        run_in(t, calls=calls)
    urls = [u for u, _ in calls]
    assert urls.count(r.CITIES_URL) == 2 and (r.CITIES_URL, r.ACCEPT_LABELS) in calls
    assert set(urls) == {r.INDEX_URL, r.MONTHLY_URL, r.CITIES_URL, r.LATEST_URL, URL18, URL3, URL11}  # no other address


def test_run_refuses_when_table18_disagrees_with_the_index():
    with tempfile.TemporaryDirectory() as t:
        bad = edit_xlsx(T18, change_cell("Data1", "A2331876F", 1973, 6, 7.5))
        msg = raises(run_in, t, t18=bad)
        assert "disagree" in msg and "1973-Q2" in msg
        assert not (Path(t) / "metrics" / "rents").exists()


def test_run_refuses_when_table3_disagrees_or_the_latest_differs():
    with tempfile.TemporaryDirectory() as t:
        assert "2025-08" in raises(run_in, t, t3=edit_xlsx(T3, change_cell("Data1", "A130390095C", 2025, 8, 3.6)))
        assert "differ" in raises(run_in, t, t3=edit_xlsx(T3, delete_row("Data1", 2025, 9)))
        assert "differ" in raises(run_in, t, t18=edit_xlsx(T18, delete_row("Data1", 1974, 12)))


def test_run_refuses_a_city_that_disagrees_and_writes_nothing():
    with tempfile.TemporaryDirectory() as t:
        bad = edit_xlsx(T11, lambda wb: (change_cell("Data4", "A130395219K", 2025, 9, 1.0)(wb), change_cell("Data4", "A130394393X", 2025, 9, 1.0)(wb)))
        msg = raises(run_in, t, t11=bad)
        assert "Canberra" in msg and "2025-09" in msg
        assert not (Path(t) / "metrics" / "rents").exists()


def test_run_refuses_the_two_duplicate_columns_disagreeing():
    with tempfile.TemporaryDirectory() as t:
        bad = edit_xlsx(T11, change_cell("Data2", "A130399262R", 2025, 7, 4.9))
        assert "the two columns for Adelaide" in raises(run_in, t, t11=bad)


def test_run_refuses_a_gap_and_bad_downloads():
    with tempfile.TemporaryDirectory() as t:
        assert "missing quarters" in raises(run_in, t, index=without_lines(INDEX, "1973-Q1"))
        assert "missing months" in raises(run_in, t, monthly=without_lines(MONTHLY, "2025-08"))
        assert "not the series asked for" in raises(run_in, t, monthly=INDEX)
        assert "no link ending in /6401018.xlsx" in raises(run_in, t, html=b"<html></html>")
        assert "no link ending in /6401011.xlsx" in raises(run_in, t, html=edit(HTML, "6401011.xlsx", "6401012.xlsx", count=2))
        assert "HTTP 500" in raises(run_in, t, t18=a.ScrapeError("https://x answered HTTP 500"))
        assert not (Path(t) / "metrics" / "rents").exists()


def test_run_refuses_fewer_rows_than_before_for_each_series_and_jurisdiction():
    with tempfile.TemporaryDirectory() as t:
        run_in(t)
        path = Path(t) / "metrics" / "rents" / "data.csv"
        lines = path.read_text().splitlines()
        # an earlier run held one more Tasmanian month at the end, so the rows would fall
        path.write_text("\n".join(lines + ["2025-10-31,2025-10,rents_monthly,Tasmania,0.1,pct,actual"]) + "\n")
        assert "Tasmania" in raises(run_in, t) and "Rows must never fall" in raises(run_in, t)
        # an earlier run started a month before the first one now (same number of rows)
        moved = [l.replace("2025-07-31,2025-07,rents_monthly,Tasmania", "2025-06-30,2025-06,rents_monthly,Tasmania") for l in lines]
        path.write_text("\n".join(moved) + "\n")
        assert "now starts at 2025-07, later than the 2025-06" in raises(run_in, t)
        # a series the run does not produce
        path.write_text("\n".join(lines + ["2025-09-30,2025-09,rents_quarterly,Australia,3.0,pct,actual"]) + "\n")
        assert "which this run did not produce" in raises(run_in, t)


def test_main_exits_1_on_failure():
    orig = r.run

    def boom(**kw):
        raise a.ScrapeError("test failure")
    r.run = boom
    try:
        assert r.main(["--root", "/nonexistent"]) == 1
    finally:
        r.run = orig


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
