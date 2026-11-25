#!/usr/bin/env python3
"""Tests for scrapers/bulk_billing.py. Plain asserts; pytest also finds them. No network. Fixtures (trimmed copies of
the real RoGS 2026 section 10 files, years 2022-23 to 2024-25, real layouts):
  rogs-primary-health-trimmed.csv    tables 10A.27 (bulk billing by remoteness, the table that must not be used) and 10A.28
                                     (by age), the full set of columns
  rogs-primary-health-trimmed.xlsx   sheets 'Table 10A.27' and 'Table 10A.28' in the real layout (a year row above its
                                     figures, footnote marks on the labels)
  rogs-front.html                    the RoGS front page links
The scraper's FIRST_YEAR is set to 2022 so the trimmed files give a three-year run."""
import csv
import io
import json
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import abs_series as a  # noqa: E402
import bulk_billing as bb  # noqa: E402
import rogs  # noqa: E402

FX = HERE / "fixtures"
CSV = (FX / "rogs-primary-health-trimmed.csv").read_bytes()
XLSX = (FX / "rogs-primary-health-trimmed.xlsx").read_bytes()
FRONT = (FX / "rogs-front.html").read_bytes()
CSV_URL = "https://assets.pc.gov.au/2026-01/rogs-2026-parte-section10-primary-and-community-health-dataset_0.csv?VersionId=skSVcIjTxjuNWGWtKhp75L9zKdEohB9W"
XLSX_URL = "https://assets.pc.gov.au/2026-01/rogs-2026-parte-section10-primary-and-community-health-data-tables_0.xlsx?VersionId=dhbsbDjTKGQMTdhUt6hXYhyRTwePk28I"
P2026 = rogs.FRONT_URL + "2026/data-downloads/"
D2026 = f'<html><a href="{CSV_URL}">dataset</a><a href="{XLSX_URL}">tables</a><a href="https://assets.pc.gov.au/2026-01/rogs-2026-parte-section10-primary-and-community-health-report.pdf">pdf</a></html>'.encode()
bb.FIRST_YEAR = 2022
quiet = lambda m: None  # noqa: E731

# The selection of the stored series: table 10A.28, All ages, All people, All people, All areas.
SEL = {"Table_Number": "10A.28", "Age": "All ages"}
BY_REMOTENESS = {"Table_Number": "10A.27", "Age": "All ages", "Remoteness": "All areas"}


def raises(fn, *a_, **kw):
    try:
        fn(*a_, **kw)
    except a.ScrapeError as e:
        return str(e)
    raise AssertionError("expected ScrapeError")


def fetcher(csv_=CSV, xlsx=XLSX, d2026=D2026):
    table = {rogs.FRONT_URL: FRONT, P2026: d2026, CSV_URL: csv_, XLSX_URL: xlsx}

    def f(url, accept="*/*"):
        if url not in table:
            raise AssertionError(f"unexpected download {url}")
        return table[url]
    return f


def run_in(root, **kw):
    return bb.run(root=root, fetcher=fetcher(**kw), log=quiet)


def rows_of(root):
    return list(csv.DictReader(io.StringIO((Path(root) / "metrics/bulk-billing/data.csv").read_text())))


def to_csv(rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(rows)
    return buf.getvalue().encode("utf-8")


def edit_csv(raw, match, year, column, value):
    """Changes one figure in the CSV: the one row whose columns equal `match` in the given year."""
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    head = rows[0]
    hits = [r for r in rows[1:] if r[head.index("Year")] == year and all(r[head.index(k)] == v for k, v in match.items())]
    assert len(hits) == 1, len(hits)
    hits[0][head.index(column)] = value
    return to_csv(rows)


def change_xlsx(raw, sheet, year, column, value, label="All ages"):
    """Changes one figure in the workbook: the row whose label starts with `label` under the year row."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = wb[sheet]
    header = next(r for r in ws.iter_rows(min_row=1, max_row=4) if any(c.value == "Unit" for c in r))
    col = next(c.column for c in header if c.value and str(c.value).replace("\xa0", " ").startswith(column))
    seen_year = False
    for r in ws.iter_rows(min_row=1):
        texts = [str(c.value) for c in r[:11] if c.value is not None]
        if year in texts:
            seen_year = True
            continue
        if seen_year and any(t.startswith(label) for t in texts) and r[11].value:
            ws.cell(r[0].row, col).value = value
            break
    else:
        raise AssertionError("cell not found")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- a full run

def test_a_full_run_selects_the_series_dates_it_and_keeps_australia_only():
    with tempfile.TemporaryDirectory() as root:
        out = run_in(root)
        rows = rows_of(root)
        assert len(rows) == 3  # one series, Australia only, three years
        assert [(r["period"], r["date"], r["value"]) for r in sorted(rows, key=lambda r: r["date"])] == [
            ("2022-23", "2023-06-30", "80.2"), ("2023-24", "2024-06-30", "77.3"), ("2024-25", "2025-06-30", "77.9")]
        assert all((r["series"], r["jurisdiction"], r["unit"], r["status"]) == ("gp_bulk_billed_pct", "Australia", "pct", "actual") for r in rows)
        assert out["checked"] == {"gp_bulk_billed_pct": 3}  # 3 years x 1 column, CSV against the workbook
        assert out["codes"] == []
        man = json.loads((Path(root) / "metrics/bulk-billing/sources/manifest.json").read_text())
        assert man["rogs-editions"] == {"editions": {"2022-23": "2026", "2023-24": "2026", "2024-25": "2026"}}
        assert man["rogs-2026-parte-section10-primary-and-community-health-data-tables_0.xlsx"]["url"] == XLSX_URL
        assert (Path(root) / "metrics/bulk-billing/sources/rogs-2026-parte-section10-primary-and-community-health-dataset_0.csv").read_bytes() == CSV  # byte for byte


def test_a_second_run_is_byte_identical():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        files = lambda: {p.name: p.read_bytes() for p in (Path(root) / "metrics/bulk-billing").rglob("*") if p.is_file()}  # noqa: E731
        one = files()
        run_in(root)
        assert files() == one


# ---------------------------------------------------------------- selection: table 10A.27 is never used

def test_the_selection_is_the_all_ages_all_areas_row_of_table_10a28():
    ds = rogs.parse_dataset(CSV)
    where = {**SEL, **{k: v for k, v in bb.SERIES["gp_bulk_billed_pct"]["where"].items()}}
    got = rogs.select(ds, where, ["2024-25"], columns=["Aust"])
    assert got == {"2024-25": {"Aust": "77.9"}}
    # the other ages in the same table have other figures: the Age column is part of the selection
    assert rogs.select(ds, {**where, "Age": "65+ years old"}, ["2024-25"], columns=["Aust"]) == {"2024-25": {"Aust": "87.3"}}
    assert bb.SERIES["gp_bulk_billed_pct"]["table"] == "10A.28"


def test_table_10a27_is_never_used_even_though_it_matches_every_other_column():
    ds = rogs.parse_dataset(CSV)
    other = {k: v for k, v in bb.SERIES["gp_bulk_billed_pct"]["where"].items()}
    # without the table number there are two rows for the year (10A.28 and the All areas row of 10A.27): the loader refuses
    assert "2 rows match" in raises(rogs.select, ds, other, ["2024-25"], columns=["Aust"])
    # 10A.27 has no state figures at all, and its All areas row is a different table
    assert "neither a number nor one of the codes" in raises(rogs.select, ds, {**other, "Table_Number": "10A.27"}, ["2024-25"], columns=["NSW"])
    assert all(s["table"] != "10A.27" for s in bb.SERIES.values())
    # changing the 10A.27 figure changes nothing stored
    with tempfile.TemporaryDirectory() as root:
        out = run_in(root, csv_=edit_csv(CSV, BY_REMOTENESS, "2024-25", "Aust", "70.0"))
        assert out["selected"]["gp_bulk_billed_pct"]["2024-25"]["Aust"] == "77.9"
        assert next(r for r in rows_of(root) if r["period"] == "2024-25")["value"] == "77.9"
    # with the 10A.28 rows gone and only 10A.27 left, the run refuses rather than falling back to 10A.27
    rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
    head = rows[0]
    kept = [rows[0]] + [r for r in rows[1:] if r[head.index("Table_Number")] != "10A.28"]
    with tempfile.TemporaryDirectory() as root:
        msg = raises(run_in, root, csv_=to_csv(kept))
        assert "gp_bulk_billed_pct" in msg and "10A.28" in msg
        assert not (Path(root) / "metrics").exists()


# ---------------------------------------------------------------- refusals

def test_the_run_refuses_and_writes_nothing_when_the_workbook_disagrees():
    with tempfile.TemporaryDirectory() as root:
        bad = change_xlsx(XLSX, "Table 10A.28", "2024-25", "Aust", 78.0)
        msg = raises(run_in, root, xlsx=bad)
        assert "gp_bulk_billed_pct" in msg and "2024-25 Aust: CSV 77.9, workbook 78" in msg
        assert not (Path(root) / "metrics").exists()
        # an older year too
        bad = change_xlsx(XLSX, "Table 10A.28", "2022-23", "Aust", 80.3)
        assert "2022-23 Aust: CSV 80.2, workbook 80.3" in raises(run_in, root, xlsx=bad)
    with tempfile.TemporaryDirectory() as root:
        # a CSV figure that differs from the workbook
        msg = raises(run_in, root, csv_=edit_csv(CSV, SEL | bb.SERIES["gp_bulk_billed_pct"]["where"], "2023-24", "Aust", "77.4"))
        assert "2023-24 Aust: CSV 77.4, workbook 77.3" in msg
        assert not (Path(root) / "metrics").exists()


def test_a_code_in_a_cell_must_agree_between_the_csv_and_the_workbook_and_is_stored_as_a_code():
    match = {**bb.SERIES["gp_bulk_billed_pct"]["where"], "Table_Number": "10A.28"}
    with tempfile.TemporaryDirectory() as root:
        # the CSV says na and the workbook has a number
        msg = raises(run_in, root, csv_=edit_csv(CSV, match, "2024-25", "Aust", "na"))
        assert "2024-25 Aust: CSV na, workbook 77.9" in msg
        # the CSV has a number and the workbook says np
        msg = raises(run_in, root, xlsx=change_xlsx(XLSX, "Table 10A.28", "2024-25", "Aust", "np"))
        assert "workbook np" in msg
        # text that is neither a number nor a code, or an empty cell, is refused
        assert "neither a number nor one of the codes" in raises(run_in, root, csv_=edit_csv(CSV, match, "2024-25", "Aust", "n/a"))
        assert "neither a number nor one of the codes" in raises(run_in, root, csv_=edit_csv(CSV, match, "2024-25", "Aust", ""))
        assert not (Path(root) / "metrics").exists()
        # a code that both files carry is stored as a code, never as a number
        out = run_in(root, csv_=edit_csv(CSV, match, "2024-25", "Aust", "np"), xlsx=change_xlsx(XLSX, "Table 10A.28", "2024-25", "Aust", "np"))
        assert next(r for r in rows_of(root) if r["period"] == "2024-25")["value"] == "np"
        assert out["codes"] == [("gp_bulk_billed_pct", "2024-25", "Australia", "np")]


def test_the_number_of_decimal_places_is_checked():
    match = {**bb.SERIES["gp_bulk_billed_pct"]["where"], "Table_Number": "10A.28"}
    with tempfile.TemporaryDirectory() as root:
        msg = raises(run_in, root, csv_=edit_csv(CSV, match, "2024-25", "Aust", "78"))
        assert "gp_bulk_billed_pct" in msg and "1 decimal place" in msg
        msg = raises(run_in, root, csv_=edit_csv(CSV, match, "2024-25", "Aust", "77.95"))
        assert "'77.95'" in msg
        assert not (Path(root) / "metrics").exists()


def test_a_changed_unit_or_missing_selection_or_a_year_gap_is_refused():
    with tempfile.TemporaryDirectory() as root:
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"%"', b'"no."'))  # the unit is part of the selection
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"All areas"', b'"All regions"'))
        rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
        head = rows[0]
        is_mine = lambda r: r[head.index("Table_Number")] == "10A.28" and r[head.index("Age")] == "All ages"  # noqa: E731
        # a duplicate row: two rows for one year and selection
        dup = next(r for r in rows[1:] if is_mine(r) and r[head.index("Year")] == "2024-25")
        assert "2 rows match" in raises(run_in, root, csv_=to_csv(rows + [dup]))
        # a missing year in the middle
        gap = [rows[0]] + [r for r in rows[1:] if not (is_mine(r) and r[head.index("Year")] == "2023-24")]
        assert "not consecutive" in raises(run_in, root, csv_=to_csv(gap))
        assert not (Path(root) / "metrics").exists()


# ---------------------------------------------------------------- history

def test_rows_for_years_the_new_edition_drops_are_kept_and_revisions_come_from_the_new_edition():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        path = Path(root) / "metrics/bulk-billing/data.csv"
        text = path.read_text()
        text = text.replace("2025-06-30,2024-25,gp_bulk_billed_pct,Australia,77.9,pct,actual", "2025-06-30,2024-25,gp_bulk_billed_pct,Australia,1.0,pct,actual")
        text += "2022-06-30,2021-22,gp_bulk_billed_pct,Australia,88.3,pct,actual\n"
        path.write_text(text)
        mp = Path(root) / "metrics/bulk-billing/sources/manifest.json"
        man = json.loads(mp.read_text())
        man["rogs-editions"] = {"editions": {"2021-22": "2025", "2022-23": "2026", "2023-24": "2026", "2024-25": "2026"}}
        mp.write_text(json.dumps(man))
        run_in(root)
        rows = rows_of(root)
        assert [r["value"] for r in rows if r["period"] == "2021-22"] == ["88.3"]  # kept unchanged
        assert next(r for r in rows if r["period"] == "2024-25")["value"] == "77.9"  # the new edition's figure
        # without the manifest's note for a kept year the run refuses and writes nothing
        man["rogs-editions"] = {"editions": {"2022-23": "2026"}}
        mp.write_text(json.dumps(man))
        before = path.read_bytes()
        assert "does not say which edition" in raises(run_in, root)
        assert path.read_bytes() == before


def test_main_returns_1_and_says_nothing_was_written_on_a_failure():
    orig = bb.run
    try:
        bb.run = lambda **kw: (_ for _ in ()).throw(a.ScrapeError("boom"))
        assert bb.main(["--root", "/nonexistent"]) == 1
    finally:
        bb.run = orig


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
