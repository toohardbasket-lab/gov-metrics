#!/usr/bin/env python3
"""Tests for scrapers/hospital_waits.py. Plain asserts; pytest also finds them. No network. Fixtures (trimmed copies
of the real RoGS 2026 section 12 files, years 2022-23 to 2024-25, real layouts):
  rogs-hospitals-trimmed.csv    tables 12A.13, 12A.18, 12A.23 and 12A.24 (the two 12A.24 rows per year and percentile that
                                match every other column of the 12A.23 selection), the full set of columns
  rogs-hospitals-trimmed.xlsx   sheets 'Table 12A.13', 'Table 12A.18', 'Table 12A.23' in the real layout (a year row above
                                its figures, footnote marks, two column sets in 12A.23), each sheet declared as one cell (A1)
  rogs-front.html               the RoGS front page links
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
import hospital_waits as hw  # noqa: E402
import rogs  # noqa: E402

FX = HERE / "fixtures"
CSV = (FX / "rogs-hospitals-trimmed.csv").read_bytes()
XLSX = (FX / "rogs-hospitals-trimmed.xlsx").read_bytes()
FRONT = (FX / "rogs-front.html").read_bytes()
CSV_URL = "https://assets.pc.gov.au/2026-01/rogs-2026-parte-section12-public-hospitals-dataset_0.csv?VersionId=orWdM_Bmd55MYtts.IPogG9IhAhHK2DC"
XLSX_URL = "https://assets.pc.gov.au/2026-01/rogs-2026-parte-section12-public-hospitals-data-tables_0.xlsx?VersionId=pLHy2VkM3lw2Y69pK2Ogj15_a5XCdQ3O"
P2026 = rogs.FRONT_URL + "2026/data-downloads/"
D2026 = f'<html><a href="{CSV_URL}">dataset</a><a href="{XLSX_URL}">tables</a><a href="https://assets.pc.gov.au/2026-01/rogs-2026-parte-section12-public-hospitals-report.pdf">pdf</a></html>'.encode()
hw.FIRST_YEAR = 2022
quiet = lambda m: None  # noqa: E731


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
    return hw.run(root=root, fetcher=fetcher(**kw), log=quiet)


def rows_of(root):
    return list(csv.DictReader(io.StringIO((Path(root) / "metrics/hospital-waits/data.csv").read_text())))


def edit_csv(raw, series_cols, year, column, value, nth=0):
    """Changes one figure in the CSV: the rows of the given table whose columns equal series_cols, the year, the column."""
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    head = rows[0]
    hits = [r for r in rows[1:] if r[head.index("Year")] == year and all(r[head.index(k)] == v for k, v in series_cols.items())]
    hits[nth][head.index(column)] = value
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(rows)
    return buf.getvalue().encode("utf-8")


def change_xlsx(raw, sheet, label, year, column, value, group=None, unit=None):
    """Changes one figure in the workbook: the first row whose label starts with `label` below the year row (and below
    the row for `group`, a hospital group, when one is given) and whose Unit is `unit`, when one is given."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    ws = wb[sheet]
    header = next(r for r in ws.iter_rows(min_row=1, max_row=4) if any(c.value == "Unit" for c in r))
    col = next(c.column for c in header if c.value and str(c.value).replace("\xa0", " ").startswith(column))
    seen_year, seen_group = False, group is None
    for r in ws.iter_rows(min_row=1):
        texts = [str(c.value) for c in r[:11] if c.value is not None]
        if year in texts:
            seen_year = True
            continue
        if seen_year and group is not None and any(t.startswith(group) for t in texts) and not r[11].value:
            seen_group = True
            continue
        if seen_year and seen_group and any(t.startswith(label) for t in texts) and r[11].value and (unit is None or r[11].value == unit):
            ws.cell(r[0].row, col).value = value
            break
    else:
        raise AssertionError("cell not found")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SEEN = {"Table_Number": "12A.13", "Description3": "Patients seen on time", "Triage_Category": "Total excluding unknown triage category"}
FOUR = {"Table_Number": "12A.18", "Description3": "ED stay length is within four hours", "Unit": "%"}
MEDIAN = {"Table_Number": "12A.23", "Hospital_Sector_Grp": "All public hospitals", "Description3": "50th percentile", "Description5": "Total"}


# ---------------------------------------------------------------- a full run

def test_a_full_run_selects_each_series_dates_it_and_stores_codes_as_codes():
    with tempfile.TemporaryDirectory() as root:
        out = run_in(root)
        rows = rows_of(root)
        assert len(rows) == 4 * 9 * 3  # four series, nine jurisdictions, three years
        get = lambda s, j, y: next(r for r in rows if (r["series"], r["jurisdiction"], r["period"]) == (s, j, y))  # noqa: E731
        # each series, Australia 2024-25, dated 30 June of the second year
        for sid, want, unit in [("ed_seen_on_time", "67", "pct"), ("ed_within_4_hours", "53.4", "pct"), ("surgery_median_days", "45", "days"), ("surgery_90th_days", "329", "days")]:
            r = get(sid, "Australia", "2024-25")
            assert (r["value"], r["unit"], r["date"], r["status"]) == (want, unit, "2025-06-30", "actual"), (sid, r)
        assert get("ed_seen_on_time", "Western Australia", "2024-25")["value"] == "46"
        assert get("ed_within_4_hours", "Victoria", "2022-23")["value"] == "52.0"  # as published: the one decimal is kept
        assert get("ed_seen_on_time", "Victoria", "2022-23")["value"] == "65"  # as published: no decimal added
        assert get("surgery_median_days", "Northern Territory", "2023-24")["value"] == "na"  # a code stays a code
        assert get("surgery_90th_days", "Northern Territory", "2023-24")["value"] == "na"
        assert out["checked"] == {s: 27 for s in hw.SERIES}  # 3 years x 9 columns each, CSV against the workbook
        assert out["codes"] == [("surgery_90th_days", "2023-24", "Northern Territory", "na"), ("surgery_median_days", "2023-24", "Northern Territory", "na")]
        man = json.loads((Path(root) / "metrics/hospital-waits/sources/manifest.json").read_text())
        assert man["rogs-editions"] == {"editions": {"2022-23": "2026", "2023-24": "2026", "2024-25": "2026"}}
        assert "rogs-2026-parte-section12-public-hospitals-dataset_0.csv" in man and man["rogs-2026-parte-section12-public-hospitals-data-tables_0.xlsx"]["url"] == XLSX_URL
        assert (Path(root) / "metrics/hospital-waits/sources/rogs-2026-parte-section12-public-hospitals-dataset_0.csv").read_bytes() == CSV  # byte for byte


def test_a_second_run_is_byte_identical():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        files = lambda: {p.name: p.read_bytes() for p in (Path(root) / "metrics/hospital-waits").rglob("*") if p.is_file()}  # noqa: E731
        one = files()
        run_in(root)
        assert files() == one


def test_the_workbook_is_read_although_it_declares_each_sheet_as_one_cell():
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(XLSX))
    assert b'<dimension ref="A1"/>' in z.read("xl/worksheets/sheet4.xml")
    assert len(rogs.read_workbook(XLSX, "12A.23", group="50th percentile", unit_in_path=True)) > 10


# ---------------------------------------------------------------- table 12A.24 is not used

def test_table_12a24_is_never_used_even_though_it_matches_every_other_column():
    ds = rogs.parse_dataset(CSV)
    other = {k: v for k, v in MEDIAN.items() if k != "Table_Number"}
    # without the table number there are three rows for the year (12A.23 and the two of 12A.24): the loader refuses
    assert "3 rows match" in raises(rogs.select, ds, {**other, "Measure": "Elective surgery: waiting times", "Unit": "days"}, ["2024-25"])
    with tempfile.TemporaryDirectory() as root:
        out = run_in(root)
        # 12A.24 holds 59 (all patients with the Indigenous breakdown) for Australia 2024-25 in the real file; 12A.23's figure is 45
        assert out["selected"]["surgery_median_days"]["2024-25"]["Aust"] == "45"
        assert all(r["value"] != "59" for r in rows_of(root) if r["series"] == "surgery_median_days" and r["period"] == "2024-25" and r["jurisdiction"] == "Australia")
    assert all(s["table"] != "12A.24" for s in hw.SERIES.values())
    # with the 12A.23 rows gone and only 12A.24 left, the run refuses rather than falling back to 12A.24
    rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
    head = rows[0]
    kept = [rows[0]] + [r for r in rows[1:] if r[head.index("Table_Number")] != "12A.23"]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(kept)
    with tempfile.TemporaryDirectory() as root:
        msg = raises(run_in, root, csv_=buf.getvalue().encode("utf-8"))
        assert "surgery_median_days" in msg and "12A.23" in msg
        assert not (Path(root) / "metrics").exists()


# ---------------------------------------------------------------- refusals

def test_the_run_refuses_and_writes_nothing_when_the_workbook_disagrees():
    with tempfile.TemporaryDirectory() as root:
        bad = change_xlsx(XLSX, "Table 12A.13", "Total", "2024-25", "WA", 47)
        msg = raises(run_in, root, xlsx=bad)
        assert "ed_seen_on_time" in msg and "2024-25 WA: CSV 46, workbook 47" in msg
        assert not (Path(root) / "metrics").exists()
        bad = change_xlsx(XLSX, "Table 12A.23", "Total", "2024-25", "Aust", 46, group="All public hospitals")  # the 50th percentile columns
        msg = raises(run_in, root, xlsx=bad)
        assert "surgery_median_days" in msg and "2024-25 Aust: CSV 45, workbook 46" in msg
        assert not (Path(root) / "metrics").exists()
        # the 90th percentile columns are read as their own set: a change there is a disagreement for that series only
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(XLSX))
        ws = wb["Table 12A.23"]
        header = next(r for r in ws.iter_rows(min_row=1, max_row=4) if any(c.value == "Unit" for c in r))
        aust = [c.column for c in header if c.value and str(c.value).startswith("Aust")]
        assert len(aust) == 2
        wrong = "329"
        for r in ws.iter_rows(min_row=1):
            if r[11].value == "days" and ws.cell(r[0].row, aust[1]).value is not None and str(ws.cell(r[0].row, aust[1]).value) == wrong:
                ws.cell(r[0].row, aust[1]).value = 330
        buf = io.BytesIO()
        wb.save(buf)
        msg = raises(run_in, root, xlsx=buf.getvalue())
        assert "surgery_90th_days" in msg and "CSV 329, workbook 330" in msg


def test_a_code_in_a_cell_must_agree_between_the_csv_and_the_workbook():
    with tempfile.TemporaryDirectory() as root:
        # the CSV says na and the workbook has a number
        bad = change_xlsx(XLSX, "Table 12A.23", "Total", "2023-24", "NT", 31, group="All public hospitals")
        msg = raises(run_in, root, xlsx=bad)
        assert "2023-24 NT: CSV na, workbook 31" in msg
        # the CSV has a number and the workbook says np
        bad = change_xlsx(XLSX, "Table 12A.18", "ED stay length", "2024-25", "SA", "np", unit="%")
        assert "workbook np" in raises(run_in, root, xlsx=bad)
        # text that is neither a number nor a code is refused
        bad_csv = edit_csv(CSV, {k: v for k, v in SEEN.items()}, "2024-25", "Tas", "n/a")
        assert "neither a number nor one of the codes" in raises(run_in, root, csv_=bad_csv)
        bad_csv = edit_csv(CSV, SEEN, "2024-25", "Tas", "")
        assert "neither a number nor one of the codes" in raises(run_in, root, csv_=bad_csv)
        assert not (Path(root) / "metrics").exists()


def test_the_number_of_decimal_places_is_checked_so_the_page_never_shows_one_the_source_lacks():
    with tempfile.TemporaryDirectory() as root:
        msg = raises(run_in, root, csv_=edit_csv(CSV, SEEN, "2024-25", "Aust", "67.4"))
        assert "ed_seen_on_time" in msg and "'67.4'" in msg and "0 decimal place" in msg
        msg = raises(run_in, root, csv_=edit_csv(CSV, FOUR, "2024-25", "Aust", "53"))
        assert "ed_within_4_hours" in msg and "1 decimal place" in msg
        assert not (Path(root) / "metrics").exists()


def test_a_changed_unit_or_missing_selection_or_a_year_gap_is_refused():
    with tempfile.TemporaryDirectory() as root:
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"days"', b'"weeks"'))  # the unit is part of every selection
        # a selection that matches nothing (the Measure text changed)
        assert "no rows match" in raises(run_in, root, csv_=CSV.replace(b'"Patients staying for four hours or less"', b'"Patients staying four hours or less"'))
        # a duplicate row: two rows for one year and selection
        rows = list(csv.reader(io.StringIO(CSV.decode("utf-8"))))
        head = rows[0]
        dup = next(r for r in rows[1:] if all(r[head.index(k)] == v for k, v in SEEN.items()) and r[head.index("Year")] == "2024-25")
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(rows + [dup])
        assert "2 rows match" in raises(run_in, root, csv_=buf.getvalue().encode("utf-8"))
        # a missing year in the middle
        gap = [rows[0]] + [r for r in rows[1:] if not (r[head.index("Year")] == "2023-24" and r[head.index("Table_Number")] == "12A.13")]
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL).writerows(gap)
        assert "not consecutive" in raises(run_in, root, csv_=buf.getvalue().encode("utf-8"))
        assert not (Path(root) / "metrics").exists()


def test_financial_years_are_dated_30_june_of_the_second_year():
    assert hw.financial_year("2024-25") == (2024, "2025-06-30")
    assert hw.financial_year("1999-00") == (1999, "2000-06-30")
    assert "not two consecutive years" in raises(hw.financial_year, "2015-17")
    assert "not a financial year" in raises(hw.financial_year, "2016")
    hw.check_years(["2022-23", "2023-24", "2024-25"])
    assert "not consecutive" in raises(hw.check_years, ["2022-23", "2024-25"])


# ---------------------------------------------------------------- history

def test_rows_for_years_the_new_edition_drops_are_kept_and_revisions_come_from_the_new_edition():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        path = Path(root) / "metrics/hospital-waits/data.csv"
        text = path.read_text()
        extra = "\n".join(f"2022-06-30,2021-22,{s},Australia,1,{hw.SERIES[s]['unit']},actual" for s in hw.SERIES) + "\n"
        text = text.replace("2025-06-30,2024-25,surgery_median_days,Australia,45,days,actual", "2025-06-30,2024-25,surgery_median_days,Australia,1,days,actual") + extra
        path.write_text(text)
        mp = Path(root) / "metrics/hospital-waits/sources/manifest.json"
        man = json.loads(mp.read_text())
        man["rogs-editions"] = {"editions": {"2021-22": "2025", "2022-23": "2026", "2023-24": "2026", "2024-25": "2026"}}
        mp.write_text(json.dumps(man))
        run_in(root)
        rows = rows_of(root)
        kept = [r for r in rows if r["period"] == "2021-22"]
        assert len(kept) == 4 and all(r["value"] == "1" for r in kept)  # unchanged
        assert next(r for r in rows if r["series"] == "surgery_median_days" and r["jurisdiction"] == "Australia" and r["period"] == "2024-25")["value"] == "45"
        # without the manifest's note for a kept year the run refuses and writes nothing
        man["rogs-editions"] = {"editions": {"2022-23": "2026"}}
        mp.write_text(json.dumps(man))
        before = path.read_bytes()
        assert "does not say which edition" in raises(run_in, root)
        assert path.read_bytes() == before


def test_rows_never_fall():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        path = Path(root) / "metrics/hospital-waits/data.csv"
        path.write_text(path.read_text() + "2020-06-30,2019-20,ed_seen_on_time,Australia,74,pct,actual\n")
        mp = Path(root) / "metrics/hospital-waits/sources/manifest.json"
        man = json.loads(mp.read_text())
        man["rogs-editions"]["editions"]["2019-20"] = "2025"
        mp.write_text(json.dumps(man))
        run_in(root)  # a kept older year is fine
        assert any(r["period"] == "2019-20" for r in rows_of(root))


def test_main_returns_1_and_says_nothing_was_written_on_a_failure():
    orig = hw.run
    try:
        hw.run = lambda **kw: (_ for _ in ()).throw(a.ScrapeError("boom"))
        assert hw.main(["--root", "/nonexistent"]) == 1
    finally:
        hw.run = orig


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
