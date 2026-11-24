#!/usr/bin/env python3
"""Tests for scrapers/social_housing.py. Plain asserts; pytest also finds them. No network. Uses the trimmed
fixtures of test_rogs.py and the ERP ones (abs-erp-api-trimmed.csv, abs-erp-labels-trimmed.csv,
abs-erp-table4-trimmed.xlsx: six quarters 2024-Q1 to 2025-Q2, abs-erp-decoy-trimmed.xlsx, abs-population-latest-release.html).
The scraper's FIRST_YEAR is set to 2024 so the trimmed files (RoGS years 2016, 2024, 2025) give a two-year run."""
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
import rogs  # noqa: E402
import social_housing as sh  # noqa: E402
import test_rogs as tr  # noqa: E402

FX = HERE / "fixtures"
ERP = (FX / "abs-erp-api-trimmed.csv").read_bytes()
LABELS = (FX / "abs-erp-labels-trimmed.csv").read_bytes()
T4 = (FX / "abs-erp-table4-trimmed.xlsx").read_bytes()
DECOY = (FX / "abs-erp-decoy-trimmed.xlsx").read_bytes()
POP_HTML = (FX / "abs-population-latest-release.html").read_bytes()
POP_BASE = "https://www.abs.gov.au/statistics/people/population/national-state-and-territory-population/mar-2026/"
CSV_URL = "https://assets.pc.gov.au/2026-06/rogs-202606-partg-section18-housing-dataset.csv?VersionId=452PrARedO_yz90HVzrm.K8XZVpBQnNn"
XLSX_URL = "https://assets.pc.gov.au/2026-06/rogs-202606-partg-section18-housing-data-tables.xlsx?VersionId=o7kJ9f3Oaf6x6zuQDKjAACwLyKf.fDqe"
sh.FIRST_YEAR = 2024
quiet = lambda m: None  # noqa: E731
raises = tr.raises
edit = tr.edit


def fetcher(csv_=tr.CSV, xlsx=tr.XLSX, erp=ERP, labels=LABELS, t4=T4, pop_html=POP_HTML, d2026=tr.D2026, calls=None):
    pages = tr.pages(d2026=d2026)

    def f(url, accept="*/*"):
        if calls is not None:
            calls.append(url)
        table = {CSV_URL: csv_, XLSX_URL: xlsx, sh.POP_PAGE: pop_html, POP_BASE + "310104.xlsx": t4,
                 POP_BASE + "310101.xlsx": DECOY, POP_BASE + "3101051.xlsx": DECOY}
        if url == sh.ERP_URL:
            return labels if accept == sh.ERP_LABELS else erp
        if url in table:
            return table[url]
        return pages(url, accept)
    return f


def run_in(root, **kw):
    return sh.run(root=root, fetcher=fetcher(**kw), log=quiet)


def rows_of(root):
    return list(csv.DictReader(io.StringIO((Path(root) / "metrics/social-housing/data.csv").read_text())))


def test_a_full_run_writes_rows_sources_and_the_edition_map():
    with tempfile.TemporaryDirectory() as root:
        out = run_in(root)
        rows = rows_of(root)
        assert len(rows) == 4 * 9 * 2 + 9 * 2  # four dwelling series and population, nine jurisdictions, 2024 and 2025
        get = lambda s, j, y: next(r for r in rows if (r["series"], r["jurisdiction"], r["period"]) == (s, j, y))  # noqa: E731
        assert get("public_housing", "Australia", "2025")["value"] == "296541" and get("public_housing", "Australia", "2025")["date"] == "2025-06-30"
        assert get("somih", "Victoria", "2025")["value"] == ".."  # a code stays a code
        assert get("community_housing", "Australia", "2025")["value"] == "118425"  # tenancy units, not dwellings (114206)
        assert get("population", "Australia", "2025")["value"] == "27601739" and get("population", "Australia", "2025")["unit"] == "count"
        assert out["summary"]["Australia"] == ("450607", "16.3")
        assert out["checked"] == {s: 18 for s in sh.SELECTIONS} and out["june_total"] == 9 * 2
        man = json.loads((Path(root) / "metrics/social-housing/sources/manifest.json").read_text())
        assert man["rogs-editions"] == {"editions": {"2024": "2026", "2025": "2026"}}
        assert "rogs-202606-partg-section18-housing-dataset.csv" in man and (Path(root) / "metrics/social-housing/sources/abs-erp-310104.xlsx").exists()
        assert man["abs-erp-310104.xlsx"]["url"] == POP_BASE + "310104.xlsx"


def test_a_second_run_is_byte_identical():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        files = lambda: {p.name: p.read_bytes() for p in (Path(root) / "metrics/social-housing").rglob("*") if p.is_file()}  # noqa: E731
        one = files()
        run_in(root)
        assert files() == one


def test_rows_for_years_the_new_edition_drops_are_kept_and_revisions_come_from_the_new_edition():
    with tempfile.TemporaryDirectory() as root:
        run_in(root)
        path = Path(root) / "metrics/social-housing/data.csv"
        text = path.read_text()
        # stored data has an extra old year (2023, from the 2025 edition), and 2025 public housing Australia differs from the new edition
        extra = "\n".join(f"2023-06-30,2023,{s},Australia,1000,count,actual" for s in sh.DWELLING_SERIES) + "\n"
        text = text.replace("2025-06-30,2025,public_housing,Australia,296541,count,actual", "2025-06-30,2025,public_housing,Australia,1,count,actual") + extra
        path.write_text(text)
        mp = Path(root) / "metrics/social-housing/sources/manifest.json"
        man = json.loads(mp.read_text())
        man["rogs-editions"] = {"editions": {"2023": "2025", "2024": "2026", "2025": "2026"}}
        mp.write_text(json.dumps(man))
        run_in(root)
        rows = rows_of(root)
        kept = [r for r in rows if r["period"] == "2023"]
        assert len(kept) == 4 and all(r["value"] == "1000" for r in kept)  # unchanged
        assert next(r for r in rows if r["series"] == "public_housing" and r["jurisdiction"] == "Australia" and r["period"] == "2025")["value"] == "296541"
        eds = json.loads(mp.read_text())["rogs-editions"]["editions"]
        assert eds == {"2023": "2025", "2024": "2026", "2025": "2026"}
        # without the manifest's note for a kept year the run refuses and writes nothing
        man["rogs-editions"] = {"editions": {"2024": "2026"}}
        mp.write_text(json.dumps(man))
        before = path.read_bytes()
        assert "does not say which edition" in raises(run_in, root)
        assert path.read_bytes() == before


def test_the_run_refuses_and_writes_nothing_when_the_workbook_disagrees():
    with tempfile.TemporaryDirectory() as root:
        bad = tr._change_cell(tr.XLSX, ["Indigenous community housing"], "2025", "Qld", 5407)
        msg = raises(run_in, root, xlsx=bad)
        assert "indigenous_community_housing" in msg and "2025 Qld: CSV 5406, workbook 5407" in msg
        assert not (Path(root) / "metrics").exists()


def test_the_run_refuses_when_population_disagrees_with_the_spreadsheet_or_a_region_is_misnamed():
    import openpyxl
    with tempfile.TemporaryDirectory() as root:
        wb = openpyxl.load_workbook(io.BytesIO(T4))
        ws = wb["Data1"]
        hdr = next(r for r in ws.iter_rows(min_row=10, max_row=10))
        col = next(c.column for c in hdr if c.value == "A2060842F")
        for r in ws.iter_rows(min_row=11):
            if r[0].value.year == 2025 and r[0].value.month == 6:
                ws.cell(r[0].row, col).value += 1
        buf = io.BytesIO()
        wb.save(buf)
        msg = raises(run_in, root, t4=buf.getvalue())
        assert "Australia" in msg and "2025-Q2" in msg and "disagree" in msg
        swapped = LABELS.replace(b"5: Western Australia", b"5: Victoria")
        assert "not named as expected" in raises(run_in, root, labels=swapped)
        assert not (Path(root) / "metrics").exists()
    assert "not named as expected" in raises(sh.check_names, LABELS.replace(b"7: Northern Territory", b"7: Tasmania"), ERP)
    assert "do not hold the same figures" in raises(sh.check_names, LABELS, ERP.replace(b"27601739", b"27601738"))


def test_the_population_workbook_is_found_by_its_headers_and_refused_if_none_or_two():
    links = sh.sheet_links(POP_HTML, sh.POP_PAGE)
    assert [l.rsplit("/", 1)[-1] for l in links] == ["310101.xlsx", "310104.xlsx", "3101051.xlsx"]
    url, raw, ids = sh.find_population_workbook(links, fetcher(), quiet)
    assert url.endswith("310104.xlsx") and set(ids) == set(sh.REGIONS.values()) and ids["Australia"][1] == "A2060842F"
    assert "0 workbooks" in raises(sh.find_population_workbook, links, lambda u, accept="*/*": DECOY, quiet)
    assert "2 workbooks" in raises(sh.find_population_workbook, links[:2], lambda u, accept="*/*": T4, quiet)
    assert "no link to a 3101" in raises(sh.sheet_links, b"<html></html>", sh.POP_PAGE)
    assert "not an https address on www.abs.gov.au" in raises(sh.sheet_links, b'<a href="https://evil.example.com/310104.xlsx">x</a>', sh.POP_PAGE)


def test_worked_out_figures_follow_the_code_rules():
    assert sh.worked_out(["10", "..", "-", "5"], "1000") == ("15", "15.0")
    assert sh.worked_out(["10", "na", "0", "5"], "1000") == (None, None)
    assert sh.worked_out(["1", "0", "0", "0"], "8") == ("1", "125.0")
    assert sh.worked_out(["1", "0", "0", "0"], "3") == ("1", "333.3")
    assert sh.worked_out(["5", "0", "0", "0"], "16000") == ("5", "0.3")  # 0.3125 rounds to 0.3
    assert sh.worked_out(["1", "0", "0", "0"], "16000") == ("1", "0.1")  # 0.0625 rounds to 0.1
    assert sh.worked_out(["1", "0", "0", "0"], "np")[1] is None


def test_main_returns_1_and_writes_nothing_on_failure():
    orig = sh.run

    def boom(**kw):
        raise a.ScrapeError("test failure")
    sh.run = boom
    try:
        assert sh.main(["--root", "/nonexistent"]) == 1
    finally:
        sh.run = orig


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
