#!/usr/bin/env python3
"""Tests for scrapers/inflation.py and the quarterly and blank-DECIMALS parts of scrapers/abs_series.py.
Plain asserts, no pytest needed.

Run from the project folder:  python3 scrapers/tests/test_inflation.py

No network. Small trimmed copies of the real files are in fixtures/:
  inflation-g1-trimmed.csv              Reserve Bank table G1: its real header rows, the headline column for
                                        1949-Q1 to 1951-Q4, the trimmed mean column for 2001-Q1 to 2002-Q4,
                                        and the empty future-dated row and blank row the real file ends with
  abs-cpi-index-api-trimmed.csv         the ABS quarterly CPI index, 1949-Q1 to 1951-Q4
  abs-cpi-trimmed-mean-api-trimmed.csv  the ABS trimmed mean, 2001-Q1 to 2002-Q4
  abs-cpi-monthly-api-trimmed.csv       the ABS monthly CPI year-ended change, April to September 2025
  abs-cpi-table1-trimmed.xlsx           Table 1 with the national and Sydney year-ended columns, same months
  abs-cpi-latest-release.html           the real 640101 .. 64010 links
Variants for the refusal cases are made in the tests by editing those bytes or building a small workbook.
The real G1 has one more year-ended difference in the trimmed mean before 2002 than this fixture shows
(34 in all); the fixture has one (2001-Q2: ABS 2.9, G1 3.0).
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
import inflation as inf  # noqa: E402
import openpyxl  # noqa: E402

FX = HERE / "fixtures"
G1 = (FX / "inflation-g1-trimmed.csv").read_bytes()
INDEX = (FX / "abs-cpi-index-api-trimmed.csv").read_bytes()
TRIMMED = (FX / "abs-cpi-trimmed-mean-api-trimmed.csv").read_bytes()
MONTHLY = (FX / "abs-cpi-monthly-api-trimmed.csv").read_bytes()
XLSX = (FX / "abs-cpi-table1-trimmed.xlsx").read_bytes()
HTML = (FX / "abs-cpi-latest-release.html").read_bytes()
quiet = lambda msg: None  # noqa: E731
SHEET_URL = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/sep-2026/640101.xlsx"
TABLE_HEADER = "Percentage Change from Corresponding Month of Previous Year ;  All groups CPI ;  Australia ;"


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {getattr(fn, '__name__', fn)}")


def edit(raw, old, new, count=1):
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode()
    assert old in text, old
    out = text.replace(old, new, count)
    return ("﻿" + out).encode("utf-8") if raw[:3] == b"\xef\xbb\xbf" else out.encode()


def without_lines(raw, needle):
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode()
    kept = [l for l in text.splitlines() if needle not in l]
    assert len(kept) < len(text.splitlines()), needle
    out = "\n".join(kept) + "\n"
    return ("﻿" + out).encode("utf-8") if raw[:3] == b"\xef\xbb\xbf" else out.encode()


def make_sheet(rows, header=TABLE_HEADER, sid="A130393721F", series_type="Original", unit="Percent", extra_same_header=False):
    """A small workbook shaped like Table 1. rows is [(datetime, value)]."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data1"
    heads = [None, "Index Numbers ;  All groups CPI ;  Australia ;", header]
    if extra_same_header:
        heads.append(header)
    ws.append(heads)
    n = len(heads) - 1
    ws.append(["Unit", "Index Numbers", unit] + ["Percent"] * (n - 2))
    ws.append(["Series Type", "Original", series_type] + ["Original"] * (n - 2))
    ws.append(["Data Type", "INDEX", "PERCENT"] + ["PERCENT"] * (n - 2))
    ws.append(["Frequency", "Month", "Month"] + ["Month"] * (n - 2))
    ws.append(["Collection Month", 1, 1] + [1] * (n - 2))
    ws.append(["Series Start", rows[0][0], rows[0][0]] + [rows[0][0]] * (n - 2))
    ws.append(["Series End", rows[-1][0], rows[-1][0]] + [rows[-1][0]] * (n - 2))
    ws.append(["No. Obs", len(rows), len(rows)] + [len(rows)] * (n - 2))
    ws.append(["Series ID", "A130393720C", sid] + ["A130397376A"] * (n - 2))
    for d, v in rows:
        ws.append([d, 100.0, v] + [v] * (n - 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sheet_rows():
    """The fixture's own national year-ended rows, as [(datetime, value)]."""
    wb = openpyxl.load_workbook(io.BytesIO(XLSX), data_only=True)
    return [(r[0], r[2]) for r in wb["Data1"].iter_rows(min_row=11, values_only=True)]


def fake_fetcher(g1=G1, index=INDEX, trimmed=TRIMMED, monthly=MONTHLY, html=HTML, xlsx=XLSX, calls=None):
    def f(url, accept="*/*"):
        if calls is not None:
            calls.append(url)
        table = {inf.G1_URL: g1, inf.INDEX_URL: index, inf.TRIMMED_URL: trimmed, inf.MONTHLY_URL: monthly,
                 inf.LATEST_URL: html, SHEET_URL: xlsx}
        if url not in table:
            raise AssertionError(f"unexpected download {url}")
        v = table[url]
        if isinstance(v, Exception):
            raise v
        return v
    return f


# ---------------------------------------------------------------- quarters and blank DECIMALS (abs_series.py)

def test_quarter_helpers():
    assert a.quarter_end("1950-Q1") == "1950-03-31"
    assert a.quarter_end("1950-Q2") == "1950-06-30"
    assert a.quarter_end("1950-Q3") == "1950-09-30"
    assert a.quarter_end("2026-Q4") == "2026-12-31"
    raises(a.quarter_end, "2026-Q5")
    raises(a.quarter_end, "2026-09")
    assert a.next_quarter("2025-Q4") == "2026-Q1" and a.next_quarter("2026-Q2") == "2026-Q3"
    assert a.previous_quarter("2026-Q3", 4) == "2025-Q3"
    assert a.previous_quarter("1950-Q1", 4) == "1949-Q1"
    assert a.previous_quarter("2026-Q1", 1) == "2025-Q4"
    raises(a.previous_quarter, "2026-09", 4)


def test_quarterly_series_parses_and_rejects_monthly_labels():
    s = a.parse_sdmx_series(TRIMMED, inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    assert [p for p, _ in s.pairs] == ["2001-Q1", "2001-Q2", "2001-Q3", "2001-Q4", "2002-Q1", "2002-Q2", "2002-Q3", "2002-Q4"]
    assert dict(s.pairs)["2001-Q2"] == "2.9"
    assert "unexpected period" in raises(a.parse_sdmx_series, TRIMMED, inf.EXPECTED_TRIMMED, freq="M", blank_decimals=1)
    assert "unexpected period" in raises(a.parse_sdmx_series, MONTHLY, inf.EXPECTED_MONTHLY, freq="Q", blank_decimals=1)
    raises(a.parse_sdmx_series, TRIMMED, inf.EXPECTED_TRIMMED, freq="X")


def test_blank_decimals_are_refused_by_default_and_never_rounded():
    # the ABS CPI dataflows leave DECIMALS empty: the default refuses (as for the Labour Force scraper)
    assert "DECIMALS" in raises(a.parse_sdmx_series, TRIMMED, inf.EXPECTED_TRIMMED, freq="Q")
    # with blank_decimals=1 a whole number is written with one decimal ...
    m = a.parse_sdmx_series(edit(MONTHLY, ",2025-06,1.9,", ",2025-06,2,"), inf.EXPECTED_MONTHLY, freq="M", blank_decimals=1)
    assert dict(m.pairs)["2025-06"] == "2.0"
    # ... but a figure with two decimals is refused, not rounded
    msg = raises(a.parse_sdmx_series, edit(MONTHLY, ",2025-06,1.9,", ",2025-06,1.95,"), inf.EXPECTED_MONTHLY, freq="M", blank_decimals=1)
    assert "2 decimal places" in msg and "nothing is rounded" in msg
    # raw keeps the API's text (the quarterly index has two decimals)
    s = a.parse_sdmx_series(INDEX, inf.EXPECTED_INDEX, freq="Q", blank_decimals="raw")
    assert dict(s.pairs)["1950-Q1"] == dict(s.raw_values)["1950-Q1"] and "." in dict(s.pairs)["1950-Q1"]
    # a filled DECIMALS cell is used as before (the Labour Force form), with no blank_decimals needed
    filled = edit(TRIMMED, ",2001-Q2,2.9,PCT,,,", ",2001-Q2,2.94,PCT,,1,")
    assert "DECIMALS" in raises(a.parse_sdmx_series, TRIMMED, inf.EXPECTED_TRIMMED, freq="Q")
    filled = filled.replace(b",PCT,,,", b",PCT,,1,")      # DECIMALS filled on every row
    assert dict(a.parse_sdmx_series(filled, inf.EXPECTED_TRIMMED, freq="Q").pairs)["2001-Q2"] == "2.9"   # 2.94 rounded to 1 place


def test_quarterly_series_refusals():
    msg = raises(a.parse_sdmx_series, without_lines(TRIMMED, ",2001-Q4,"), inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    assert "missing quarters 2001-Q4" in msg
    lines = TRIMMED.decode().splitlines()
    dup = ("\n".join(lines + [lines[3]]) + "\n").encode()
    assert "appears twice" in raises(a.parse_sdmx_series, dup, inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    for col, old, new in (("MEASURE", ",3,999902,", ",1,999902,"), ("INDEX", ",999902,", ",999903,"), ("TSEST", ",20,50,", ",10,50,"),
                          ("REGION", ",50,Q,", ",1,Q,"), ("FREQ", ",50,Q,", ",50,M,")):
        msg = raises(a.parse_sdmx_series, edit(TRIMMED, old, new, count=8), inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
        assert col in msg and "not the series asked for" in msg, msg
    assert "unreadable value" in raises(a.parse_sdmx_series, edit(TRIMMED, ",2001-Q2,2.9,", ",2001-Q2,abc,"), inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    assert "unreadable value" in raises(a.parse_sdmx_series, edit(TRIMMED, ",2001-Q2,2.9,", ",2001-Q2,,"), inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    assert "unexpected period" in raises(a.parse_sdmx_series, edit(TRIMMED, "2001-Q2", "2001-Q5"), inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)


# ---------------------------------------------------------------- the Reserve Bank's G1

def test_parse_g1_fixture_skips_blank_and_future_rows():
    g = inf.parse_g1(G1, [inf.G1_HEADLINE_ID, inf.G1_TRIMMED_ID])
    head, trim = g[inf.G1_HEADLINE_ID], g[inf.G1_TRIMMED_ID]
    assert min(head) == "1949-Q1" and max(head) == "1951-Q4" and len(head) == 12
    assert min(trim) == "2001-Q1" and max(trim) == "2002-Q4" and len(trim) == 8
    assert "2027-Q1" not in head and "2027-Q1" not in trim       # the empty future-dated row
    assert head["1949-Q1"] == "9.9"                               # the file's own text, not reformatted


def test_parse_g1_refusals():
    ids = [inf.G1_HEADLINE_ID, inf.G1_TRIMMED_ID]
    assert "Series ID" in raises(inf.parse_g1, edit(G1, "Series ID,", "Series IDs,"), ids)
    assert "appears 0 times" in raises(inf.parse_g1, G1, ["GCPIXXXX"])
    assert "appears 2 times" in raises(inf.parse_g1, edit(G1, "Series ID,GCPIAG,GCPIAGYP,GCPIOCPMTMYP", "Series ID,GCPIAG,GCPIAGYP,GCPIAGYP"), [inf.G1_HEADLINE_ID])
    assert "date like" in raises(inf.parse_g1, edit(G1, "30/06/1949", "1949-06-30"), ids)
    assert "not the last day of a quarter" in raises(inf.parse_g1, edit(G1, "30/06/1949", "29/06/1949"), ids)
    assert "appears twice" in raises(inf.parse_g1, edit(G1, "30/06/1949", "31/03/1949"), ids)
    assert "unreadable value" in raises(inf.parse_g1, _g1_with_value("31/03/1950", "n/a"), ids)
    assert "missing quarters 1950-Q2" in raises(inf.parse_g1, _g1_without_row("30/06/1950"), ids)
    raises(inf.parse_g1, b"\xff\xfe\x00\x01", ids)


def _g1_lines():
    return G1.decode("utf-8-sig").splitlines()


def _g1_with_value(date, value, col=2):
    out = []
    for l in _g1_lines():
        if l.startswith(date + ","):
            c = l.split(",")
            c[col] = value
            l = ",".join(c)
        out.append(l)
    return ("﻿" + "\n".join(out) + "\n").encode("utf-8")


def _g1_without_row(date):
    return ("﻿" + "\n".join(l for l in _g1_lines() if not l.startswith(date + ",")) + "\n").encode("utf-8")


# ---------------------------------------------------------------- cross-check 1: headline against the ABS index

def headline_inputs():
    g = inf.parse_g1(G1, [inf.G1_HEADLINE_ID, inf.G1_TRIMMED_ID])[inf.G1_HEADLINE_ID]
    idx = a.parse_sdmx_series(INDEX, inf.EXPECTED_INDEX, freq="Q", blank_decimals="raw")
    return g, idx


def test_headline_check_agrees_on_the_fixtures_and_drops_1949():
    g, idx = headline_inputs()
    assert inf.check_headline_against_index(g, idx, quiet) == (8, "1950-Q1", "1951-Q4")   # 1949 is not checked or kept


def test_headline_check_refuses_a_disagreeing_quarter():
    g, idx = headline_inputs()
    g["1950-Q3"] = "3.9" if g["1950-Q3"] != "3.9" else "4.0"
    msg = raises(inf.check_headline_against_index, g, idx, quiet)
    assert "disagree in 1 quarter" in msg and "1950-Q3" in msg


def test_headline_check_refuses_a_different_latest_quarter():
    g, idx = headline_inputs()
    g2 = dict(g)
    del g2["1951-Q4"]
    msg = raises(inf.check_headline_against_index, g2, idx, quiet)
    assert "latest quarter differs" in msg and "1951-Q3" in msg and "1951-Q4" in msg
    idx2 = a.parse_sdmx_series(without_lines(INDEX, ",1951-Q4,"), inf.EXPECTED_INDEX, freq="Q", blank_decimals="raw")
    assert "latest quarter differs" in raises(inf.check_headline_against_index, g, idx2, quiet)


def test_headline_check_needs_the_index_four_quarters_back_and_the_first_quarter():
    g, _ = headline_inputs()
    idx = a.parse_sdmx_series(without_lines(INDEX, ",1949-Q1,"), inf.EXPECTED_INDEX, freq="Q", blank_decimals="raw")
    assert "no figure for 1949-Q1" in raises(inf.check_headline_against_index, g, idx, quiet)
    g2 = {p: v for p, v in g.items() if p != "1950-Q1"}
    idx2 = a.parse_sdmx_series(INDEX, inf.EXPECTED_INDEX, freq="Q", blank_decimals="raw")
    assert "no figure for 1950-Q1" in raises(inf.check_headline_against_index, g2, idx2, quiet)


def test_headline_check_rounds_half_up_not_bankers():
    # 100 -> 102.25 is exactly 2.25 per cent: half up gives 2.3, banker's rounding would give 2.2
    idx = a.SdmxSeries([("1949-Q1", "100"), ("1949-Q2", "100"), ("1949-Q3", "100"), ("1949-Q4", "100"), ("1950-Q1", "102.25")], {}, {})
    g = {"1949-Q1": "0.0", "1950-Q1": "2.3"}
    assert inf.check_headline_against_index(g, idx, quiet) == (1, "1950-Q1", "1950-Q1")
    g["1950-Q1"] = "2.2"
    assert "ABS index gives 2.3" in raises(inf.check_headline_against_index, g, idx, quiet)


def test_one_decimal_never_rounds():
    assert inf.one_decimal("3", "x") == "3.0" and inf.one_decimal("3.8", "x") == "3.8" and inf.one_decimal("-0.5", "x") == "-0.5"
    assert "more than one decimal place" in raises(inf.one_decimal, "3.85", "G1 value")


# ---------------------------------------------------------------- cross-check 2: trimmed mean against G1

def trimmed_inputs():
    t = a.parse_sdmx_series(TRIMMED, inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    g = inf.parse_g1(G1, [inf.G1_HEADLINE_ID, inf.G1_TRIMMED_ID])[inf.G1_TRIMMED_ID]
    return t, g


def test_trimmed_check_reports_pre_2002_differences_without_refusing():
    t, g = trimmed_inputs()
    lines = []
    res = inf.check_trimmed_against_g1(t.pairs, g, lines.append)
    assert res["compared"] == 8 and res["agree"] == 7 and res["agree_from_2002"] == 4
    assert res["differences"] == [("2001-Q2", "2.9", "3.0", inf.Decimal("0.1"))]
    assert res["largest"] == inf.Decimal("0.1")
    text = "\n".join(lines)
    assert "before 2002-Q1 where the ABS and G1 differ: 1" in text and "2001-Q2: ABS 2.9, G1 3.0, difference 0.1" in text
    assert "all 4 quarters from 2002-Q1 agree" in text


def test_trimmed_check_counts_the_largest_of_several_differences():
    t, g = trimmed_inputs()
    g["2001-Q3"] = "3.3"          # ABS 3.1: a difference of 0.2
    res = inf.check_trimmed_against_g1(t.pairs, g, quiet)
    assert len(res["differences"]) == 2 and res["largest"] == inf.Decimal("0.2")


def test_trimmed_check_refuses_a_difference_from_2002():
    t, g = trimmed_inputs()
    g["2002-Q2"] = "3.0"
    msg = raises(inf.check_trimmed_against_g1, t.pairs, g, quiet)
    assert "disagree in 1 quarter(s) from 2002-Q1" in msg and "2002-Q2: ABS 2.9, G1 3.0" in msg
    t, g = trimmed_inputs()
    g["2002-Q1"] = "3.2"          # the first quarter of the agreement period itself
    assert "2002-Q1: ABS 3.1, G1 3.2" in raises(inf.check_trimmed_against_g1, t.pairs, g, quiet)


def test_trimmed_check_refuses_a_different_latest_quarter_or_a_quarter_missing_from_g1():
    t, g = trimmed_inputs()
    g2 = {p: v for p, v in g.items() if p != "2002-Q4"}
    assert "latest trimmed mean quarter differs" in raises(inf.check_trimmed_against_g1, t.pairs, g2, quiet)
    g3 = {p: v for p, v in g.items() if p != "2002-Q2"}
    assert "no trimmed mean figure for 2002-Q2" in raises(inf.check_trimmed_against_g1, t.pairs, g3, quiet)
    g4 = {p: v for p, v in g.items() if p != "2001-Q2"}      # before 2002 a missing G1 quarter is not a refusal
    assert inf.check_trimmed_against_g1(t.pairs, g4, quiet)["compared"] == 7
    t5 = a.parse_sdmx_series(without_lines(TRIMMED, ",2002-Q4,"), inf.EXPECTED_TRIMMED, freq="Q", blank_decimals=1)
    assert "latest trimmed mean quarter differs" in raises(inf.check_trimmed_against_g1, t5.pairs, g, quiet)


# ---------------------------------------------------------------- cross-check 3: monthly against Table 1

def test_find_the_table_link_and_the_national_column():
    assert a.find_link(HTML, inf.LATEST_URL, inf.SHEET_ENDING) == SHEET_URL       # not 6401010.xlsx and the like
    assert a.find_series_id_by_header(XLSX, inf.SHEET_HEADER_TEXT) == "A130393721F"
    sheet_values = a.parse_spreadsheet_series(XLSX, "A130393721F", expected_meta=inf.SHEET_META)
    assert len(sheet_values) == 6 and min(sheet_values) == "2025-04" and max(sheet_values) == "2025-09"


def test_column_lookup_refuses_none_or_two_matches():
    rows = sheet_rows()
    assert "0 columns" in raises(a.find_series_id_by_header, make_sheet(rows, header="Percentage Change from Previous Month ;  All groups CPI ;  Australia ;"), inf.SHEET_HEADER_TEXT)
    assert "2 columns" in raises(a.find_series_id_by_header, make_sheet(rows, extra_same_header=True), inf.SHEET_HEADER_TEXT)
    raises(a.find_series_id_by_header, b"not an excel file", inf.SHEET_HEADER_TEXT)
    # the Sydney column is not taken for the national one
    assert a.find_series_id_by_header(make_sheet(rows), inf.SHEET_HEADER_TEXT) == "A130393721F"


def test_monthly_cross_check_agrees_and_refuses():
    m = a.parse_sdmx_series(MONTHLY, inf.EXPECTED_MONTHLY, freq="M", blank_decimals=1)
    v = a.parse_spreadsheet_series(XLSX, "A130393721F", expected_meta=inf.SHEET_META)
    assert a.cross_check(m, v, quiet) == (6, "2025-04", "2025-09")
    rows = sheet_rows()
    rows[2] = (rows[2][0], rows[2][1] + 0.2)
    msg = raises(a.cross_check, m, a.parse_spreadsheet_series(make_sheet(rows), "A130393721F"), quiet)
    assert "disagree in 1 month" in msg and "2025-06" in msg
    msg = raises(a.cross_check, m, a.parse_spreadsheet_series(make_sheet(sheet_rows()[:-1]), "A130393721F"), quiet)
    assert "latest month differs" in msg
    assert "Series Type" in raises(a.parse_spreadsheet_series, make_sheet(sheet_rows(), series_type="Seasonally Adjusted"), "A130393721F", expected_meta=inf.SHEET_META)


# ---------------------------------------------------------------- the whole scraper

def run_in(root, **kw):
    return inf.run(root=root, fetcher=kw.get("fetcher") or fake_fetcher(), log=quiet)


def test_run_writes_data_sources_and_manifest_and_is_repeatable():
    with tempfile.TemporaryDirectory() as t:
        calls = []
        res = run_in(t, fetcher=fake_fetcher(calls=calls))
        assert calls == [inf.G1_URL, inf.INDEX_URL, inf.TRIMMED_URL, inf.MONTHLY_URL, inf.LATEST_URL, SHEET_URL]
        d = Path(t) / "metrics" / "inflation"
        csv1 = (d / "data.csv").read_bytes()
        lines = csv1.decode().split("\n")
        assert lines[0] == "date,period,series,jurisdiction,value,unit,status"
        assert len(lines) == 1 + 6 + 8 + 8 + 1 and lines[-1] == ""
        assert lines[1].startswith("2025-04-30,2025-04,headline_monthly,Australia,") and lines[1].endswith(",pct,actual")
        assert lines[7].startswith("1950-03-31,1950-Q1,headline_quarterly,Australia,")
        assert lines[15].startswith("2001-03-31,2001-Q1,trimmed_mean_quarterly,Australia,2.7,pct,actual")
        sorted_ok = [l for l in lines[1:-1]]
        assert sorted_ok == sorted(sorted_ok, key=lambda l: (l.split(",")[2], l.split(",")[0]))
        assert res["headline_check"] == (8, "1950-Q1", "1951-Q4") and res["sheet_id"] == "A130393721F"
        # raw files byte for byte, manifest accurate
        m = json.loads((d / "sources" / "manifest.json").read_text())
        assert sorted(m) == sorted([inf.G1_NAME, inf.INDEX_NAME, inf.TRIMMED_NAME, inf.MONTHLY_NAME, inf.SHEET_NAME])
        for name, raw in ((inf.G1_NAME, G1), (inf.INDEX_NAME, INDEX), (inf.TRIMMED_NAME, TRIMMED), (inf.MONTHLY_NAME, MONTHLY), (inf.SHEET_NAME, XLSX)):
            assert (d / "sources" / name).read_bytes() == raw
            assert m[name]["bytes"] == len(raw) and len(m[name]["sha256"]) == 64
        assert m[inf.SHEET_NAME]["url"] == SHEET_URL and m[inf.G1_NAME]["url"] == inf.G1_URL
        # the same figures with the API rows in another order: identical data.csv
        def reverse(raw):
            ls = raw.decode().splitlines()
            return ("\n".join([ls[0]] + ls[1:][::-1]) + "\n").encode()
        run_in(t, fetcher=fake_fetcher(index=reverse(INDEX), trimmed=reverse(TRIMMED), monthly=reverse(MONTHLY)))
        assert (d / "data.csv").read_bytes() == csv1


def refuses_and_writes_nothing(**kw):
    with tempfile.TemporaryDirectory() as t:
        msg = raises(inf.run, root=t, fetcher=fake_fetcher(**kw), log=quiet)
        assert not (Path(t) / "metrics").exists(), "files were written although a check failed"
        return msg


def test_run_writes_nothing_when_a_cross_check_fails():
    assert "G1 and the ABS quarterly index disagree" in refuses_and_writes_nothing(g1=_g1_with_value("31/03/1950", "9.9"))
    assert "disagree in 1 quarter(s) from 2002-Q1" in refuses_and_writes_nothing(g1=_g1_with_value("30/06/2002", "3.5", col=3))
    rows = sheet_rows()
    rows[4] = (rows[4][0], rows[4][1] + 0.3)
    assert "disagree in 1 month" in refuses_and_writes_nothing(xlsx=make_sheet(rows))
    assert "latest quarter differs" in refuses_and_writes_nothing(index=without_lines(INDEX, ",1951-Q4,"))


def test_run_does_not_refuse_pre_2002_trimmed_mean_differences():
    with tempfile.TemporaryDirectory() as t:
        out = []
        inf.run(root=t, fetcher=fake_fetcher(), log=out.append)
        text = "\n".join(out)
        assert "differ: 1, largest difference 0.1 points" in text and "2001-Q2: ABS 2.9, G1 3.0" in text
        assert (Path(t) / "metrics" / "inflation" / "data.csv").exists()
        # the stored value is the ABS's own figure, not G1's
        rows = (Path(t) / "metrics" / "inflation" / "data.csv").read_text().splitlines()
        assert [r for r in rows if r.startswith("2001-06-30,2001-Q2,trimmed_mean_quarterly")][0].split(",")[4] == "2.9"


def test_run_refuses_bad_downloads_and_writes_nothing():
    assert "HTTP 503" in refuses_and_writes_nothing(index=a.ScrapeError("https://x answered HTTP 503"))
    assert "not the series asked for" in refuses_and_writes_nothing(trimmed=edit(TRIMMED, ",999902,", ",999903,", count=8))
    assert "not the series asked for" in refuses_and_writes_nothing(monthly=edit(MONTHLY, ",3,10001,10,50,M,", ",3,10001,20,50,M,", count=6))
    assert "not the series asked for" in refuses_and_writes_nothing(index=edit(INDEX, ",1,10001,", ",3,10001,", count=12))
    assert "appears twice" in refuses_and_writes_nothing(monthly=MONTHLY + MONTHLY.splitlines(keepends=True)[1])
    assert "missing months" in refuses_and_writes_nothing(monthly=without_lines(MONTHLY, ",2025-07,"), xlsx=make_sheet([r for r in sheet_rows() if r[0].month != 7]))
    assert "missing quarters" in refuses_and_writes_nothing(index=without_lines(INDEX, ",1950-Q3,"))
    assert "unreadable value" in refuses_and_writes_nothing(trimmed=edit(TRIMMED, ",2001-Q2,2.9,", ",2001-Q2,abc,"))
    assert "decimal places" in refuses_and_writes_nothing(monthly=edit(MONTHLY, ",2025-05,2.1,", ",2025-05,2.14,"))
    assert "appears 0 times" in refuses_and_writes_nothing(g1=edit(G1, "Series ID,GCPIAG,GCPIAGYP,GCPIOCPMTMYP", "Series ID,GCPIAG,GCPIAGXX,GCPIOCPMTMYP"))
    assert "no link ending in /640101.xlsx" in refuses_and_writes_nothing(html=b"<html></html>")
    two = HTML + b'<a href="/statistics/other/nov-2026/640101.xlsx">x</a>'
    assert "more than one link" in refuses_and_writes_nothing(html=two)
    assert "0 columns" in refuses_and_writes_nothing(xlsx=make_sheet(sheet_rows(), header="Index ;  All groups CPI ;  Australia ;"))


def test_run_refuses_a_g1_value_with_two_decimals():
    msg = refuses_and_writes_nothing(g1=_g1_with_value("31/03/1950", "2.65"))
    assert "more than one decimal place" in msg


def test_run_refuses_fewer_rows_than_before_for_each_series():
    with tempfile.TemporaryDirectory() as t:
        run_in(t)
        path = Path(t) / "metrics" / "inflation" / "data.csv"
        before = path.read_bytes()
        # monthly loses its last month (the spreadsheet and API both end a month earlier, so every check passes)
        f = fake_fetcher(monthly=without_lines(MONTHLY, ",2025-09,"), xlsx=make_sheet(sheet_rows()[:-1]))
        assert "headline monthly CPI now has 5 rows, fewer than the 6" in raises(inf.run, root=t, fetcher=f, log=quiet)
        # trimmed mean loses its last quarter (and so does G1's column)
        g1 = _g1_with_value("31/12/2002", "", col=3)
        f = fake_fetcher(trimmed=without_lines(TRIMMED, ",2002-Q4,"), g1=g1)
        assert "trimmed mean (quarterly) now has 7 rows, fewer than the 8" in raises(inf.run, root=t, fetcher=f, log=quiet)
        assert path.read_bytes() == before


def test_run_refuses_a_series_that_starts_later_than_before():
    with tempfile.TemporaryDirectory() as t:
        run_in(t)
        path = Path(t) / "metrics" / "inflation" / "data.csv"
        before = path.read_bytes()
        # April is gone and October is new: the same number of rows, but the series starts later
        new_line = [l for l in MONTHLY.decode().splitlines() if ",2025-09," in l][0].replace(",2025-09,", ",2025-10,")
        monthly = (without_lines(MONTHLY, ",2025-04,").decode() + new_line + "\n").encode()
        rows = sheet_rows()[1:] + [(datetime(2025, 10, 1), 3.8)]
        new_line_val = new_line.split(",")[7]
        rows[-1] = (rows[-1][0], float(new_line_val))
        f = fake_fetcher(monthly=monthly, xlsx=make_sheet(rows))
        assert "now starts at 2025-05, later than the 2025-04" in raises(inf.run, root=t, fetcher=f, log=quiet)
        assert path.read_bytes() == before


def test_main_exits_1_on_failure():
    orig = inf.run

    def boom(**kw):
        raise a.ScrapeError("test failure")
    inf.run = boom
    try:
        assert inf.main(["--root", "/nonexistent"]) == 1
    finally:
        inf.run = orig


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
