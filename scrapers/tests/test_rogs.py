#!/usr/bin/env python3
"""Tests for scrapers/rogs.py (the reusable Report on Government Services loader). Plain asserts; pytest
also finds them. No network. Small trimmed copies of the real 2026 files are in fixtures/:
  rogs-housing-trimmed.csv        table 18A.3 for 2016, 2024 and 2025 (and one 18A.1 row), all columns of the real file
  rogs-housing-trimmed.xlsx       the real layout of sheet 'Table 18A.3' (footnote marks, year in column C), the same years
  rogs-front.html                 the front page links, rogs-downloads-2026.html, rogs-downloads-2025.html
Variants for the refusal cases are made in the tests by editing those bytes.
"""
import io
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import abs_series as a  # noqa: E402
import rogs  # noqa: E402
import openpyxl  # noqa: E402

FX = HERE / "fixtures"
CSV = (FX / "rogs-housing-trimmed.csv").read_bytes()
XLSX = (FX / "rogs-housing-trimmed.xlsx").read_bytes()
FRONT = (FX / "rogs-front.html").read_bytes()
D2026 = (FX / "rogs-downloads-2026.html").read_bytes()
D2025 = (FX / "rogs-downloads-2025.html").read_bytes()
BASE = {"Table_Number": "18A.3", "Measure": "Descriptive data"}
SLUGS = ["section18-housing-dataset", "section18-housing-data-tables"]
FRONT_URL = rogs.FRONT_URL
P2026 = FRONT_URL + "2026/data-downloads/"
P2025 = FRONT_URL + "2025/data-downloads/"
quiet = lambda m: None  # noqa: E731


def raises(fn, *a_, **kw):
    try:
        fn(*a_, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError("expected ScrapeError")


def edit(raw, old, new, count=1):
    t = raw.decode()
    assert old in t, old
    return t.replace(old, new, count).encode()


def pages(front=FRONT, d2026=D2026, d2025=D2025):
    table = {FRONT_URL: front, P2026: d2026, P2025: d2025}

    def f(url, accept="*/*"):
        if url not in table:
            raise AssertionError(f"unexpected download {url}")
        return table[url]
    return f


# ---------------------------------------------------------------- discovery

def test_discovery_takes_the_newest_year_and_the_one_link_for_each_slug():
    d = rogs.discover(pages(), SLUGS, log=quiet)
    assert d.edition == "2026" and d.fell_back_from is None
    assert d.files["section18-housing-dataset"].endswith("rogs-202606-partg-section18-housing-dataset.csv?VersionId=452PrARedO_yz90HVzrm.K8XZVpBQnNn")
    assert d.files["section18-housing-data-tables"].startswith("https://assets.pc.gov.au/2026-06/")
    assert rogs.newest_editions(FRONT) == [2026, 2025, 2024]


def test_discovery_falls_back_to_the_previous_year_and_says_so():
    lines = []
    d = rogs.discover(pages(d2026=b"<html><a href='https://assets.pc.gov.au/2026-06/rogs-x-section19-homelessness-dataset.csv'>x</a></html>"), SLUGS, log=lines.append)
    assert d.edition == "2025" and d.fell_back_from == "2026"
    assert d.files["section18-housing-dataset"].endswith("rogs-202506-partg-section18-housing-dataset.csv")
    assert any("2026" in l and "2025" in l and "instead" in l for l in lines), lines


def test_discovery_refuses_two_matches_none_and_a_foreign_host():
    two = D2026 + b'<a href="https://assets.pc.gov.au/2026-06/rogs-202606-partg-section18-housing-dataset-v2.csv">again</a>'
    assert "more than one link" in raises(rogs.discover, pages(d2026=two), SLUGS, log=quiet)
    assert "no link for" in raises(rogs.discover, pages(d2026=b"<html></html>", d2025=b"<html></html>"), SLUGS, log=quiet)
    evil = edit(D2026, "https://assets.pc.gov.au/2026-06/rogs-202606-partg-section18-housing-dataset.csv", "https://evil.example.com/2026-06/rogs-202606-partg-section18-housing-dataset.csv")
    assert "not an https address" in raises(rogs.discover, pages(d2026=evil), SLUGS, log=quiet)
    assert "no /<year>/data-downloads/ link" in raises(rogs.discover, pages(front=b"<html></html>"), SLUGS, log=quiet)


# ---------------------------------------------------------------- the CSV and its codes

def test_codes_are_kept_as_codes_and_numbers_as_written():
    ds = rogs.parse_dataset(CSV)
    sel = rogs.select(ds, {**BASE, "Description1": "State owned and managed Indigenous housing"}, ["2016", "2025"])
    assert sel["2025"]["Vic"] == ".." and sel["2025"]["NSW"] == "6552" and sel["2025"]["Aust"] == "17163"
    assert sel["2016"]["NT"] == "na"
    assert rogs.is_code("..") and rogs.is_code("na") and not rogs.is_code("0")
    assert rogs.normalise_cell("–") == "-" and rogs.normalise_cell(" np ") == "np" and rogs.normalise_cell("0") == "0"
    assert rogs.normalise_cell("12 ") == "12"
    for bad in ("", "1,234", "n/a", "x"):
        raises(rogs.normalise_cell, bad)


def test_an_empty_cell_in_a_selected_column_is_refused_but_an_unselected_one_is_not():
    ds = rogs.parse_dataset(CSV)
    where = {**BASE, "Description1": "Public housing"}
    assert rogs.select(ds, where, ["2025"], columns=["NSW", "Aust"])["2025"]["Aust"] == "296541"
    assert "neither a number nor one of the codes" in raises(rogs.select, ds, where, ["2025"], columns=["NSW", "Total"])


def test_selection_must_match_exactly_one_row_per_year():
    ds = rogs.parse_dataset(CSV)
    # community housing without Description3 matches two rows (tenancy units and dwellings) each year
    msg = raises(rogs.select, ds, {**BASE, "Description1": "Community housing"}, ["2025"])
    assert "2 rows match" in msg and "2025" in msg
    # no row at all
    assert "0 rows match" in raises(rogs.select, ds, {**BASE, "Description1": "Public housing"}, ["2023"])
    assert "0 rows match" in raises(rogs.select, ds, {**BASE, "Description1": "No such housing"}, ["2025"])
    # a duplicated row is refused too
    lines = CSV.decode().splitlines()
    dup = next(l for l in lines if l.startswith('"18A.3","2025"') and '"Public housing"' in l)
    two = (CSV.decode().rstrip("\n") + "\n" + dup + "\n").encode()
    assert "2 rows match" in raises(rogs.select, rogs.parse_dataset(two), {**BASE, "Description1": "Public housing"}, ["2025"])
    # the exact one asked for
    tu = rogs.select(ds, {**BASE, "Description1": "Community housing", "Description3": "Number of Tenancy (Rental) Units"}, ["2025"])
    assert tu["2025"]["Aust"] == "118425"
    assert "has no column" in raises(rogs.select, ds, {"Nope": "x"}, ["2025"])


def test_a_csv_with_missing_columns_or_ragged_rows_is_refused():
    assert "lacks the columns" in raises(rogs.parse_dataset, CSV.replace(b'"Aust"', b'"Australia"'))
    assert "fields" in raises(rogs.parse_dataset, CSV + b'"18A.3","2025"\n')
    assert "empty" in raises(rogs.parse_dataset, b"")


# ---------------------------------------------------------------- the workbook

def test_workbook_labels_footnotes_and_layout_are_read():
    assert rogs.clean_label("NSW (c)") == "NSW" and rogs.clean_label("Public housing (i), (j)") == "Public housing"
    assert rogs.clean_label("Number of Tenancy (Rental) Units (k), (l)") == "Number of Tenancy (Rental) Units"
    wb = rogs.read_workbook(XLSX, "18A.3")
    paths = {p for p, _, _ in wb}
    assert ("Community housing", "Number of Tenancy (Rental) Units") in paths and ("Public housing",) in paths
    cell = next(c for p, y, c in wb if p == ("Public housing",) and y == "2025")
    assert cell["Aust"] == "296541" and cell["NSW"] == "92709"
    assert rogs.description_path({**BASE, "Description1": "Community housing", "Description3": "Number of Tenancy (Rental) Units"}) == ("Community housing", "Number of Tenancy (Rental) Units")
    assert "sheets named" in raises(rogs.read_workbook, XLSX, "18A.9")


def test_csv_and_workbook_agree_on_every_selected_figure():
    ds, wb = rogs.parse_dataset(CSV), rogs.read_workbook(XLSX, "18A.3")
    total = 0
    for extra in ({"Description1": "Public housing"}, {"Description1": "State owned and managed Indigenous housing"},
                  {"Description1": "Community housing", "Description3": "Number of Tenancy (Rental) Units"}, {"Description1": "Indigenous community housing"}):
        where = {**BASE, **extra}
        sel = rogs.select(ds, where, ["2016", "2024", "2025"])
        total += rogs.cross_check(sel, wb, rogs.description_path(where))
    assert total == 4 * 3 * 9


def _change_cell(raw, row_label_path, year, column, value):
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = wb["Table 18A.3"]
    header = next(r for r in ws.iter_rows(min_row=1, max_row=4) if any(c.value == "Unit" for c in r))
    col = next(c.column for c in header if c.value and str(c.value).replace(" ", " ").startswith(column))
    block = None
    for r in ws.iter_rows(min_row=1):
        a_, b_ = r[0].value, r[1].value
        if a_ and str(a_).startswith(row_label_path[0]):
            block = "top"
        if len(row_label_path) > 1 and b_ and str(b_).startswith(row_label_path[1]):
            block = "sub"
        if r[2].value == year and block == ("sub" if len(row_label_path) > 1 else "top"):
            ws.cell(r[0].row, col).value = value
            break
    else:
        raise AssertionError("cell not found")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_workbook_that_disagrees_with_the_csv_is_refused():
    ds = rogs.parse_dataset(CSV)
    where = {**BASE, "Description1": "Public housing"}
    sel = rogs.select(ds, where, ["2016", "2024", "2025"])
    bad = _change_cell(XLSX, ["Public housing"], "2025", "Vic", 64278)
    msg = raises(rogs.cross_check, sel, rogs.read_workbook(bad, "18A.3"), rogs.description_path(where))
    assert "2025 Vic: CSV 64277, workbook 64278" in msg and "1 figure" in msg
    # a code in the workbook where the CSV has a number
    coded = _change_cell(XLSX, ["Public housing"], "2024", "WA", "na")
    assert "2024 WA: CSV 33436, workbook na" in raises(rogs.cross_check, sel, rogs.read_workbook(coded, "18A.3"), rogs.description_path(where))
    # a different year set
    sel2 = rogs.select(ds, where, ["2024", "2025"])
    assert rogs.cross_check(sel2, rogs.read_workbook(XLSX, "18A.3"), rogs.description_path(where)) == 18  # extra workbook years are fine
    sel3 = {**sel2, "2023": sel2["2024"]}
    assert "workbook has the years" in raises(rogs.cross_check, sel3, rogs.read_workbook(XLSX, "18A.3"), rogs.description_path(where))
    # a path the workbook does not have
    assert "workbook has the years" in raises(rogs.cross_check, sel, rogs.read_workbook(XLSX, "18A.3"), ("Public housing", "Other"))


# ---------------------------------------------------------------- keeping history

def test_history_is_kept_for_years_the_new_edition_drops_and_the_edition_is_recorded():
    old = [{"period": "2015", "value": "1"}, {"period": "2016", "value": "2"}, {"period": "2017", "value": "3"}]
    new = [{"period": "2016", "value": "2"}, {"period": "2017", "value": "30"}, {"period": "2018", "value": "4"}]
    rows, eds = rogs.merge_history(old, new, {"2016", "2017", "2018"}, "2027", {"2015": "2025", "2016": "2026", "2017": "2026"})
    assert [(r["period"], r["value"]) for r in rows] == [("2015", "1"), ("2016", "2"), ("2017", "30"), ("2018", "4")]
    assert eds == {"2015": "2025", "2016": "2027", "2017": "2027", "2018": "2027"}
    assert rows[0] is old[0]  # kept unchanged
    assert "does not say which edition" in raises(rogs.merge_history, old, new, {"2016", "2017", "2018"}, "2027", {})


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
