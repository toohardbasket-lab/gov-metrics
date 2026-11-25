#!/usr/bin/env python3
"""Tests for scrapers/new_homes.py. Plain asserts; pytest also finds them. No network, and no fixture files: the
Data API responses, the ABS workbooks and the "latest release" page are built here in small form (five quarters,
2024-Q2 to 2025-Q2) with the real codes, the real header texts and the real layout (header text on row 1, then Unit,
Series Type, ... Series ID, then one row per quarter dated the first day of its last month). Variants for the refusal
cases are made by changing one thing."""
import csv
import hashlib
import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import abs_series as a  # noqa: E402
import new_homes as nh  # noqa: E402

quiet = lambda m: None  # noqa: E731
QUARTERS = ["2024-Q2", "2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2"]
CODES = list(nh.REGIONS)  # 1..8, AUS
NAME = nh.REGIONS
BASE = {c: (1000 if c == "AUS" else 100 * int(c)) for c in CODES}
HDR = "DATAFLOW,MEASURE,REGION,PRICE_ADJ,BLD_WORK_TYPE,SECTOR_OWN,TYPE_BLDG,TSEST,FREQ,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE,UNIT_MULT,OBS_STATUS,OBS_COMMENT"
LAB = "DATAFLOW,MEASURE: Measure,REGION: State,PRICE_ADJ: Price Adjustment,BLD_WORK_TYPE: Type of work,SECTOR_OWN: Sector of Ownership,TYPE_BLDG: Type of building,TSEST: Adjustment Type,FREQ: Frequency,TIME_PERIOD: Time Period,OBS_VALUE,UNIT_MEASURE: Unit of Measure,UNIT_MULT: Unit of Multiplier,OBS_STATUS: Observation Status,OBS_COMMENT: Observation Comment"
PAGE_BASE = "https://www.abs.gov.au/statistics/industry/building-and-construction/building-activity-australia/jun-2026/"
URL37, URL38, URL39 = PAGE_BASE + "87520037.xlsx", PAGE_BASE + "87520038.xlsx", PAGE_BASE + "87520039.xlsx"
POP = {"Australia": 1000000, "New South Wales": 300000, "Victoria": 250000, "Queensland": 200000, "South Australia": 70000, "Western Australia": 100000, "Tasmania": 20000, "Northern Territory": 5000, "Australian Capital Territory": 10000}


def value(code, q):
    """The figure for a region and quarter in these fixtures: a base per region plus 7 for each quarter after 2024-Q2."""
    return BASE[code] + 7 * QUARTERS.index(q)


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {getattr(fn, '__name__', fn)}")


def make_api(labels=False, override=None, drop=(), values=None):
    """SDMX CSV for the nine regions. `override` maps a constant column to another cell text; `drop` is a set of
    (code, quarter) rows left out; `values` replaces figures {(code, quarter): text}."""
    over, values = override or {}, values or {}
    out = [LAB if labels else HDR]
    for code in CODES:
        for q in QUARTERS:
            if (code, q) in drop:
                continue
            v = values.get((code, q), str(value(code, q)))
            cells = {"DATAFLOW": "ABS:BUILDING_ACTIVITY(1.0.0)", "MEASURE": "M7: Dwelling units completed" if labels else "M7", "REGION": f"{code}: {NAME[code]}" if labels else code,
                     "PRICE_ADJ": "CUR: Current Price" if labels else "CUR", "BLD_WORK_TYPE": "TOT: Total Work" if labels else "TOT", "SECTOR_OWN": "9: Total Sectors" if labels else "9",
                     "TYPE_BLDG": "TOT: All Buildings" if labels else "TOT", "TSEST": "20: Seasonally Adjusted" if labels else "20", "FREQ": "Q: Quarterly" if labels else "Q"}
            cells.update(over)
            out.append(",".join([cells["DATAFLOW"], cells["MEASURE"], cells["REGION"], cells["PRICE_ADJ"], cells["BLD_WORK_TYPE"], cells["SECTOR_OWN"], cells["TYPE_BLDG"], cells["TSEST"], cells["FREQ"],
                                 q, v, "NUM: Number" if labels else "NUM", "0: Units" if labels else "0", "", ""]))
    return ("\n".join(out) + "\n").encode()


def aus_header(sector="Total Sectors", building="Total (Type of Building)"):
    return f"Dwelling units completed ;  {sector} ;  {building} ;  Total (Type of Work) ;"


def state_header(name, sector="Total Sectors", building="Total (Type of Building)"):
    return f"Dwelling units completed ;  {name} ;  {building} ;  Total (Type of Work) ;  {sector} ;"


def make_workbook(columns, quarters=QUARTERS):
    """columns: [(header, series type, series ID, {quarter: number or None})]. Two leading quarters with no figure, as the real ones have."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data1"
    ws.append([None] + [c[0] for c in columns])
    ws.append(["Unit"] + ["Number"] * len(columns))
    ws.append(["Series Type"] + [c[1] for c in columns])
    ws.append(["Data Type"] + ["FLOW"] * len(columns))
    ws.append(["Frequency"] + ["Quarter"] * len(columns))
    ws.append(["Collection Month"] + [3] * len(columns))
    ws.append(["Series Start"] + [datetime(2024, 6, 1)] * len(columns))
    ws.append(["Series End"] + [datetime(2025, 6, 1)] * len(columns))
    ws.append(["No. Obs"] + [len(quarters)] * len(columns))
    ws.append(["Series ID"] + [c[2] for c in columns])
    ws.append([datetime(1955, 3, 1)] + [None] * len(columns))
    ws.append([datetime(1955, 6, 1)] + [None] * len(columns))
    for q in quarters:
        ws.append([datetime(int(q[:4]), int(q[6]) * 3, 1)] + [c[3].get(q) for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def series_of(code, bump=0):
    return {q: value(code, q) + bump for q in QUARTERS}


def make_wb37(**kw):
    extra = {q: 1 for q in kw.get("quarters", QUARTERS) if q not in QUARTERS}
    cols = [(aus_header(), "Seasonally Adjusted", "A_AUS_SA", {**series_of("AUS", kw.get("bump", 0)), **extra}),
            (aus_header(), "Original", "A_AUS_ORIG", series_of("AUS", 500)),  # same header, other series type: ignored
            (aus_header(sector="Private Sector"), "Seasonally Adjusted", "A_AUS_PRIV", series_of("AUS", 50)),
            (aus_header(building="Houses"), "Seasonally Adjusted", "A_AUS_HOUSES", series_of("AUS", 60))]
    if kw.get("twice"):
        cols.append((aus_header(), "Seasonally Adjusted", "A_AUS_SA_TWIN", series_of("AUS")))
    if kw.get("no_aus"):
        cols = cols[1:]
    return make_workbook(cols, kw.get("quarters", QUARTERS))


def make_wb38(changes=None, quarters=QUARTERS):
    changes = changes or {}
    cols = []
    for code in CODES[:8]:
        cols.append((state_header(NAME[code]), "Seasonally Adjusted", f"A_{code}_SA", {q: value(code, q) + changes.get(code, 0) for q in quarters}))
        cols.append((state_header(NAME[code]), "Original", f"A_{code}_ORIG", {q: value(code, q) + 99 for q in quarters}))
        cols.append((state_header(NAME[code], sector="Private Sector"), "Seasonally Adjusted", f"A_{code}_PRIV", {q: 1 for q in quarters}))
    return make_workbook(cols, quarters)


def make_wb39():
    return make_workbook([(aus_header(building="Houses"), "Original", "A_X", series_of("AUS"))])


def page(titles=None, hosts=None):
    items = titles if titles is not None else [("TABLE 36. Number of Dwelling Unit Commencements by Sector, States and Territories: Original", PAGE_BASE + "87520036.xlsx"),
                                              ("TABLE 37. Number of Dwelling Unit Completions by Sector, Australia", URL37),
                                              ("TABLE 38. Number of Dwelling Unit Completions by Sector, States and Territories", URL38),
                                              ("TABLE 39. Number of Dwelling Unit Completions by Sector, States and Territories: Original", URL39),
                                              ("TABLE 71. Value of Non-residential Building Work Completed, by Sector, Australia: Original", PAGE_BASE + "87520071.xlsx")]
    html = ["<html><body><ul>"]
    for title, url in items:
        href = url.replace("https://www.abs.gov.au", "") if url.startswith("https://www.abs.gov.au") else url
        html.append(f'<li class="field__item"><div class="d"><div class="l"><h4>{title}</h4></div><div class="r"><span><a href="{href}" download="">Download xlsx [80 KB]</a></span></div></div></li>')
    html.append("</ul></body></html>")
    return "\n".join(html).encode()


def social_csv(skip=None, extra=(), unit="count", value_override=None):
    """metrics/social-housing/data.csv with the population on 30 June 2024 for the nine jurisdictions, and decoys."""
    rows = ["date,period,series,jurisdiction,value,unit,status"]
    for j, v in POP.items():
        if j == skip:
            continue
        v = (value_override or {}).get(j, v)
        rows.append(f"2024-06-30,2024,population,{j},{v},{unit},actual")
        rows.append(f"2023-06-30,2023,population,{j},{POP[j] - 1},{unit},actual")
        rows.append(f"2024-06-30,2024,public_housing,{j},5,{unit},actual")
    rows.extend(extra)
    return ("\n".join(rows) + "\n").encode()


def fetcher(api=None, labels=None, p=None, wb37=None, wb38=None, wb39=None, calls=None):
    api = make_api() if api is None else api
    labels = make_api(labels=True) if labels is None else labels
    p = page() if p is None else p
    table = {nh.PAGE_URL: p, URL37: wb37 or make_wb37(), URL38: wb38 or make_wb38(), URL39: wb39 or make_wb39()}

    def f(url, accept="*/*"):
        if calls is not None:
            calls.append(url)
        if url == nh.API_URL:
            return labels if accept == nh.API_LABELS else api
        if url in table:
            return table[url]
        raise AssertionError(f"unexpected download {url}")
    return f


def root_with_social(**kw):
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name) / "metrics" / "social-housing"
    d.mkdir(parents=True)
    (d / "data.csv").write_bytes(social_csv(**kw))
    return tmp


def run_in(root, **kw):
    return nh.run(root=root, fetcher=fetcher(**kw), log=quiet)


def rows_of(root):
    return list(csv.DictReader(io.StringIO((Path(root) / "metrics/new-homes/data.csv").read_text())))


def nothing_written(root):
    return not (Path(root) / "metrics" / "new-homes").exists()


# ---------------------------------------------------------------- a good run

def test_a_full_run_writes_rows_the_worked_out_figures_and_the_manifest():
    with root_with_social() as root:
        out = run_in(root)
        rows = rows_of(root)
        assert len(rows) == 9 * 5 + 9  # completions for nine jurisdictions and five quarters, plus the population on 30 June 2024
        get = lambda s, j, p: next(r for r in rows if (r["series"], r["jurisdiction"], r["period"]) == (s, j, p))  # noqa: E731
        r = get("completions", "Australia", "2025-Q2")
        assert r["value"] == "1028" and r["date"] == "2025-06-30" and r["unit"] == "count" and r["status"] == "actual"
        assert get("completions", "Western Australia", "2024-Q3")["date"] == "2024-09-30" and get("completions", "Western Australia", "2024-Q3")["value"] == "507"
        assert get("completions", "Australian Capital Territory", "2024-Q2")["date"] == "2024-06-30"
        p = get("population_june_2024", "Victoria", "2024")
        assert p["value"] == "250000" and p["date"] == "2024-06-30" and p["unit"] == "count"
        # only 30 June 2024 is copied, not 2023, and nothing else from the social housing file
        assert {r["period"] for r in rows if r["series"] == "population_june_2024"} == {"2024"} and {r["series"] for r in rows} == {"completions", "population_june_2024"}
        # checked against the workbooks: every jurisdiction, every quarter, the series IDs found by header and type
        assert all(c[0] == 5 for c in out["checks"].values()) and len(out["checks"]) == 9
        assert out["ids"]["Australia"] == ("87520037.xlsx", "Data1", "A_AUS_SA") and out["ids"]["Tasmania"] == ("87520038.xlsx", "Data1", "A_6_SA")
        # worked out separately: Australia 2024-Q3..2025-Q2 is 1007+1014+1021+1028 = 4070; 4.07 per 1,000 residents -> 4.1; pace 4 of 20 quarters
        assert out["summary"]["Australia"] == (4070, "4.1") and out["to_prior"][0] == 1007 + 1014 + 1021 and out["pace"] == "240000"
        assert out["summary"]["New South Wales"] == (470, "1.6")  # 4 x 100 + 7 x (1+2+3+4) = 470; 470 / 300000 x 1000 = 1.5667
        man = json.loads((Path(root) / "metrics/new-homes/sources/manifest.json").read_text())
        copy = man["copied-from-metrics-social-housing-data.csv"]
        assert copy["path"] == "metrics/social-housing/data.csv" and copy["series"] == "population"
        assert copy["sha256"] == hashlib.sha256((Path(root) / "metrics/social-housing/data.csv").read_bytes()).hexdigest()
        assert set(man) == {nh.API_NAME, nh.LABELS_NAME, "abs-building-activity-87520037.xlsx", "abs-building-activity-87520038.xlsx", "copied-from-metrics-social-housing-data.csv"}
        for name in set(man) - {"copied-from-metrics-social-housing-data.csv"}:  # raw downloads byte for byte, with their checksums
            raw = (Path(root) / "metrics/new-homes/sources" / name).read_bytes()
            assert man[name]["sha256"] == hashlib.sha256(raw).hexdigest() and man[name]["bytes"] == len(raw)
        assert man["abs-building-activity-87520037.xlsx"]["url"] == URL37


def test_only_the_completions_workbooks_are_downloaded_and_a_second_run_is_byte_identical():
    with root_with_social() as root:
        calls = []
        run_in(root, calls=calls)
        # the commencements and non-residential tables are never fetched: the page's table titles narrow the search
        assert sorted(set(calls)) == sorted({nh.API_URL, nh.PAGE_URL, URL37, URL38, URL39})
        files = lambda: {str(p.relative_to(root)): p.read_bytes() for p in (Path(root) / "metrics/new-homes").rglob("*") if p.is_file()}  # noqa: E731
        one = files()
        run_in(root)
        assert files() == one


# ---------------------------------------------------------------- the codes

def test_every_code_is_confirmed_from_the_labelled_response_and_the_plain_one():
    with root_with_social() as root:
        # a different name for a code in the labelled response
        for col, text, word in (("SECTOR_OWN", "1: Private Sector", "SECTOR_OWN"), ("TSEST", "10: Original", "TSEST"), ("MEASURE", "M5: Dwelling units commenced", "MEASURE"),
                                ("TYPE_BLDG", "1: Houses", "TYPE_BLDG"), ("BLD_WORK_TYPE", "1: New", "BLD_WORK_TYPE"), ("PRICE_ADJ", "KP: Chain Volume", "PRICE_ADJ")):
            msg = raises(run_in, root, labels=make_api(labels=True, override={col: text}))
            assert word in msg and "expected only" in msg, msg
        # a different code in the plain response (the labelled one still says what was asked for)
        for col, code in (("SECTOR_OWN", "1"), ("TSEST", "10"), ("MEASURE", "M5"), ("TYPE_BLDG", "1"), ("BLD_WORK_TYPE", "1"), ("PRICE_ADJ", "KP")):
            msg = raises(run_in, root, api=make_api(override={col: code}))
            assert col in msg and ("not the series asked for" in msg or "do not hold the same figures" in msg), msg
        # a region with another name: Western Australia called Victoria
        msg = raises(run_in, root, labels=make_api(labels=True).replace(b"5: Western Australia", b"5: Victoria"))
        assert "not named as expected" in msg and "Building Activity" in msg
        # the labelled response with other figures from the plain one
        assert "do not hold the same figures" in raises(run_in, root, labels=make_api(labels=True, values={("AUS", "2025-Q2"): "1"}))
        assert nothing_written(root)


# ---------------------------------------------------------------- the figures

def test_a_figure_that_is_not_a_whole_number_is_refused_not_rounded():
    with root_with_social() as root:
        for bad in ("1028.5", "1028.0", "-"):
            msg = raises(run_in, root, api=make_api(values={("AUS", "2025-Q2"): bad}), labels=make_api(labels=True, values={("AUS", "2025-Q2"): bad}))
            assert "2025-Q2" in msg and ("decimal places" in msg or "unreadable value" in msg), msg
        assert nothing_written(root)


def test_a_missing_quarter_in_the_api_is_refused_and_so_are_regions_that_cover_different_quarters():
    with root_with_social() as root:
        msg = raises(run_in, root, api=make_api(drop={("3", "2024-Q4")}), labels=make_api(labels=True, drop={("3", "2024-Q4")}))
        assert "Queensland" in msg and "missing quarters 2024-Q4" in msg
        # the last quarter missing for one region: nothing is missing inside the series, but the regions end on different quarters
        msg = raises(run_in, root, api=make_api(drop={("8", "2025-Q2")}), labels=make_api(labels=True, drop={("8", "2025-Q2")}))
        assert "do not cover the same quarters" in msg
        # a region missing altogether
        gone = {(c, q) for c in ("7",) for q in QUARTERS}
        assert "not named as expected" in raises(run_in, root, api=make_api(drop=gone), labels=make_api(labels=True, drop=gone))
        assert "do not hold the same figures" in raises(run_in, root, api=make_api(drop=gone))
        assert nothing_written(root)


# ---------------------------------------------------------------- the spreadsheets

def test_the_run_refuses_and_writes_nothing_when_a_state_disagrees_with_the_spreadsheet():
    with root_with_social() as root:
        msg = raises(run_in, root, wb38=make_wb38(changes={"4": 1}))
        assert "South Australia" in msg and "A_4_SA" in msg and "disagree" in msg and "2024-Q2" in msg, msg
        msg = raises(run_in, root, wb37=make_wb37(bump=1))
        assert "Australia" in msg and "A_AUS_SA" in msg and "disagree" in msg
        assert nothing_written(root)


def test_the_api_and_a_workbook_must_cover_the_same_quarters():
    with root_with_social() as root:
        msg = raises(run_in, root, wb38=make_wb38(quarters=QUARTERS[:-1]))
        assert "cover different quarters" in msg and "only in the API ['2025-Q2']" in msg
        msg = raises(run_in, root, wb37=make_wb37(quarters=QUARTERS + ["2025-Q3"]))
        assert "cover different quarters" in msg and "only in the workbook ['2025-Q3']" in msg
        assert nothing_written(root)


def test_a_column_must_be_found_exactly_once_by_header_text_and_series_type():
    with root_with_social() as root:
        # the same seasonally adjusted header twice in one workbook
        assert "expected exactly one" in raises(run_in, root, wb37=make_wb37(twice=True))
        # no Australia column at all: the Original column with the same header is not accepted in its place
        assert "Australia: 0 workbook columns" in raises(run_in, root, wb37=make_wb37(no_aus=True))
        # the same header in two workbooks
        assert "Australia: 2 workbook columns" in raises(run_in, root, wb39=make_wb37())
        assert nothing_written(root)


def test_the_page_must_list_the_completions_tables_on_abs_gov_au():
    with root_with_social() as root:
        assert "no workbook whose table title contains" in raises(run_in, root, p=page(titles=[("TABLE 36. Number of Dwelling Unit Commencements", PAGE_BASE + "87520036.xlsx")]))
        assert "not an https address on www.abs.gov.au" in raises(run_in, root, p=page(titles=[("TABLE 37. Number of Dwelling Unit Completions by Sector, Australia", "https://example.com/87520037.xlsx")]))
        assert nothing_written(root)


def test_find_columns_finds_by_header_and_type_and_ignores_other_series():
    ids, used = nh.find_columns([("t37", URL37), ("t38", URL38), ("t39", URL39)], fetcher(), quiet)
    assert ids["Australia"] == (URL37, "Data1", "A_AUS_SA") and ids["Northern Territory"] == (URL38, "Data1", "A_7_SA")
    assert set(used) == {URL37, URL38}  # the workbook with no wanted column is not kept
    assert nh.columns_in(make_wb39()) == {}


# ---------------------------------------------------------------- the population copy

def test_the_run_refuses_when_the_population_copy_is_missing_or_wrong():
    with tempfile.TemporaryDirectory() as root:  # no social housing file at all
        assert "social housing scraper must run before this one" in raises(run_in, root)
        assert nothing_written(root)
    with root_with_social(skip="Tasmania") as root:
        msg = raises(run_in, root)
        assert "all nine jurisdictions" in msg and "Tasmania" in msg
        assert nothing_written(root)
    with root_with_social() as root:  # the file has the series, but not on 30 June 2024
        p = Path(root) / "metrics/social-housing/data.csv"
        p.write_bytes(p.read_bytes().replace(b"2024-06-30,2024,population", b"2025-06-30,2025,population"))
        assert "all nine jurisdictions" in raises(run_in, root)
    with root_with_social(value_override={"Victoria": "25.5"}) as root:
        assert "not a whole number" in raises(run_in, root)
    with root_with_social(unit="rate") as root:
        assert "expected count" in raises(run_in, root)
    with root_with_social(extra=["2024-06-30,2024,population,Victoria,250000,count,actual"]) as root:
        assert "appears twice" in raises(run_in, root)
    with root_with_social() as root:
        p = Path(root) / "metrics/social-housing/data.csv"
        p.write_bytes(p.read_bytes().replace(b"date,period", b"date,when"))
        assert "does not have the header" in raises(run_in, root)


# ---------------------------------------------------------------- history and the written file

def test_rows_never_fall():
    with root_with_social() as root:
        run_in(root)
        path = Path(root) / "metrics/new-homes/data.csv"
        before = path.read_bytes()
        # stored data has an extra earlier quarter that the new response lacks
        path.write_text(path.read_text() + "2024-03-31,2024-Q1,completions,Australia,999,count,actual\n")
        msg = raises(run_in, root)
        assert "completions (Australia)" in msg and "Rows must never fall" in msg
        # stored data has a series this run does not produce
        path.write_bytes(before + b"2024-06-30,2024,other,Australia,1,count,actual\n")
        assert "which this run did not produce" in raises(run_in, root)
        # fewer rows than stored: a later quarter the response lacks
        path.write_bytes(before + b"2025-09-30,2025-Q3,completions,Australia,1,count,actual\n")
        assert "fewer than the" in raises(run_in, root)


def test_worked_out_adds_exact_quarters_and_refuses_a_gap():
    comp = {"2024-Q3": "10", "2024-Q4": "20", "2025-Q1": "30"}
    assert nh.worked_out(comp, "3000") == (60, "20.0")
    assert nh.worked_out(comp, "3000", last="2024-Q4") == (30, "10.0")
    assert nh.worked_out({"2024-Q3": "1", "2024-Q4": "1"}, "3") == (2, "666.7")  # 666.666... rounds half up
    assert nh.worked_out({"2024-Q3": "1"}, "8000") == (1, "0.1")  # 0.125 -> 0.1; and 0.15 below
    assert nh.worked_out({"2024-Q3": "3"}, "20000") == (3, "0.2")  # 0.15 -> 0.2 (half up)
    assert "needs 2024-Q4" in raises(nh.worked_out, {"2024-Q3": "10", "2025-Q1": "30"}, "3000")
    assert nh.round_half_up_fraction(nh.Fraction(1200000 * 8, 20), 0) == "480000"


def test_the_main_function_writes_nothing_and_exits_1_on_a_refusal(capsys=None):
    with tempfile.TemporaryDirectory() as root:  # no social housing file: refuses before writing, and main() would only call the network after
        import io as _io
        orig = nh.run
        try:
            nh.run = lambda **kw: orig(root=kw["root"], fetcher=fetcher(), log=quiet)
            assert nh.main(["--root", root]) == 1
        finally:
            nh.run = orig
        assert nothing_written(root)


def main():
    import traceback
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
