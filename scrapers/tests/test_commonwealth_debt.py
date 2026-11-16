#!/usr/bin/env python3
"""Tests for scrapers/commonwealth_debt.py. Plain asserts, no pytest needed.

Run from the project folder:  python3 scrapers/tests/test_commonwealth_debt.py

Needs no network. The 2024-25 Appendix B Word file and the machine-read CSV
(the figures a language model read from the PDF) are kept in fixtures/.
"""
import csv
import io
import sys
import tempfile
import traceback
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import commonwealth_debt as cd  # noqa: E402
import docx  # noqa: E402
from docx.table import _Cell  # noqa: E402

DOCX = HERE / "fixtures" / "fbo-2024-25-appendix-b.docx"
FIXTURE_CSV = HERE / "fixtures" / "fbo-2024-25-appendix-b-machine-read.csv"
quiet = lambda msg: None  # noqa: E731


def raises(fn, *args):
    try:
        fn(*args)
    except cd.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {fn.__name__}")


# ---------------------------------------------------------------- number parser

def test_plain_numbers():
    assert cd.parse_number("344") == Decimal("344")
    assert cd.parse_number("0.9") == Decimal("0.9")
    assert cd.parse_number("0.0") == Decimal("0.0")
    assert cd.parse_number(" 12 ") == Decimal("12")


def test_thousands_separators():
    assert cd.parse_number("1,851") == Decimal("1851")
    assert cd.parse_number("971,447") == Decimal("971447")
    assert cd.parse_number("1,234,567") == Decimal("1234567")
    assert cd.parse_number("1,169.0") == Decimal("1169.0")
    raises(cd.parse_number, "1,85")      # misplaced separator
    raises(cd.parse_number, "12,34,567")


def test_negatives_in_every_dash_variant():
    variants = {
        "hyphen-minus": "-",
        "hyphen U+2010": "‐",
        "non-breaking hyphen U+2011": "‑",
        "figure dash U+2012": "‒",
        "en dash": "–",
        "em dash": "—",
        "horizontal bar": "―",
        "minus sign U+2212": "−",
        "small hyphen-minus": "﹣",
        "full-width hyphen-minus": "－",
    }
    for name, d in variants.items():
        assert cd.parse_number(f"{d}1,851") == Decimal("-1851"), name
        assert cd.parse_number(f"{d}0.5") == Decimal("-0.5"), name
        assert cd.parse_number(f"{d} 496") == Decimal("-496"), name  # space after the sign
        assert cd.parse_number(f"{d}24,288 ") == Decimal("-24288"), name


def test_footnote_markers():
    assert cd.parse_number("1,234(e)") == Decimal("1234")
    assert cd.parse_number("1,234 (a)") == Decimal("1234")
    assert cd.parse_number("−1,234(b)") == Decimal("-1234")
    assert cd.parse_number("0.5(c)") == Decimal("0.5")


def test_odd_spaces():
    assert cd.parse_number("1 234") == Decimal("1234")
    assert cd.parse_number("​-12​") == Decimal("-12")


def test_unreadable_values_fail():
    for bad in ["", "-", "–", "−", "na", "..", "abc", "1.2.3", "12a", "(1,234)", "1 2 3 x"]:
        raises(cd.parse_number, bad)


def test_year_labels():
    assert cd.parse_year_label("1970-71")[:3] == (1970, "1970-71", "")
    assert cd.parse_year_label("2010–11")[:2] == (2010, "2010-11")
    assert cd.parse_year_label("1999-00")[:2] == (1999, "1999-00")
    assert cd.parse_year_label("2024-25(e)")[3] is True       # marker noted, ignored
    assert cd.parse_year_label("2024-25 (a)")[2] == ""
    assert cd.parse_year_label("Gross debt") is None
    raises(cd.parse_year_label, "2010-13")


# ---------------------------------------------------------------- table parser

def parsed_fixture():
    return cd.parse_appendix_b(str(DOCX), "2024-25", quiet)


def test_table_parser_matches_machine_read_fixture():
    """Compares all 55 years x 4 values with the figures the language model read.

    Prints every mismatch. The test fails if there is any, because the point is to
    find out whether the machine-read prototype data was right.
    """
    info, parsed = parsed_fixture()
    assert info["net_debt"]["table"] == "B.4" and info["gross_debt"]["table"] == "B.5"
    with FIXTURE_CSV.open(newline="", encoding="utf-8") as f:
        fixture = {r["fy"]: r for r in csv.DictReader(f)}
    assert len(parsed) == 55 and len(fixture) == 55
    cols = {"gross_debt": "gross_debt_m", "net_debt": "net_debt_m",
            "gross_debt_pct_gdp": "gross_debt_pct_gdp", "net_debt_pct_gdp": "net_debt_pct_gdp"}
    mismatches, compared = [], 0
    for start in sorted(parsed):
        rec = parsed[start]
        for series, col in cols.items():
            compared += 1
            if Decimal(fixture[rec["period"]][col]) != rec[series]:
                mismatches.append((rec["period"], series, str(rec[series]), fixture[rec["period"]][col]))
    for m in mismatches:
        print("  mismatch (year, series, parsed, fixture):", m)
    assert compared == 220
    assert not mismatches, f"{len(mismatches)} of 220 values differ from the machine-read fixture"


def test_net_debt_sign_and_known_rows():
    info, parsed = parsed_fixture()
    # Net debt is negative in the early 1970s and in 2006-07 to 2008-09 (checked against the Word file by eye).
    assert parsed[1971]["net_debt"] < 0 and parsed[1971]["net_debt_pct_gdp"] < 0
    assert parsed[2006]["net_debt"] < 0
    assert parsed[1970]["net_debt"] > 0


def test_first_and_last_years():
    info, parsed = parsed_fixture()
    assert min(parsed) == 1970 and max(parsed) == 2024
    assert parsed[1970]["period"] == "1970-71" and parsed[2024]["period"] == "2024-25"


def test_build_rows_shape():
    info, parsed = parsed_fixture()
    rows = cd.build_rows(parsed)
    assert len(rows) == 220
    assert rows[0] == ["1971-06-30", "1970-71", "gross_debt", "Commonwealth", "10887", "aud_million", "actual"]
    assert {r[2] for r in rows} == {"gross_debt", "net_debt", "gross_debt_pct_gdp", "net_debt_pct_gdp"}
    assert all(r[0].endswith("-06-30") and r[6] == "actual" for r in rows)


# ---------------------------------------------------------------- failures write nothing

def edited_docx(edit):
    """The fixture, changed by edit(document), returned as bytes."""
    document = docx.Document(str(DOCX))
    edit(document)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def find_row(document, label, which="net_debt"):
    """(table, row) for the row whose first cell is label, inside the net debt
    table (Table B.4) or the AGS table (Table B.5), found by caption."""
    _, pieces = cd.find_tables(document, cd.APPENDIX_TABLES[which]["caption"])
    for table in pieces:
        for tr in table._tbl.tr_lst:
            if _Cell(tr.tc_lst[0], table).text.strip() == label:
                return table, tr
    raise AssertionError(f"row {label} not found")


def set_cell(table, tr, index, text):
    cell = _Cell(tr.tc_lst[index], table)
    runs = cell.paragraphs[0].runs
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def test_unreadable_value_fails():
    def edit(d):
        table, tr = find_row(d, "1990-91")
        set_cell(table, tr, 1, "abc")
    msg = raises(cd.parse_appendix_b, edited_docx(edit), "2024-25", quiet)
    assert "1990-91" in msg


def test_missing_year_fails():
    def edit(d):
        table, tr = find_row(d, "1990-91")
        tr.getparent().remove(tr)
    msg = raises(cd.parse_appendix_b, edited_docx(edit), "2024-25", quiet)
    assert "missing years" in msg and "1990-91" in msg


def test_duplicate_year_fails():
    def edit(d):
        table, tr = find_row(d, "1990-91")
        set_cell(table, tr, 0, "1989-90")
    msg = raises(cd.parse_appendix_b, edited_docx(edit), "2024-25", quiet)
    assert "twice" in msg


def test_table_not_found_fails():
    def edit(d):
        for p in d.paragraphs:
            if p.text.replace(" ", " ").startswith("Table B.4:"):
                for r in p.runs:
                    r.text = r.text.replace("net debt and net", "something and net")
    msg = raises(cd.parse_appendix_b, edited_docx(edit), "2024-25", quiet)
    assert "no table with a caption" in msg


def test_wrong_budget_year_fails():
    # The file ends at 2024-25, so asking for 2025-26 must fail, not pad or guess.
    msg = raises(cd.parse_appendix_b, str(DOCX), "2025-26", quiet)
    assert "last year" in msg


def test_failed_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        def fetcher(url):
            # Appendix B for 2024-25 is real; Part 1 is deliberately not a Word file.
            return DOCX.read_bytes() if "appendix_b" in url else b"not a word file"
        raises(cd.run, "2024-25", tmp, fetcher, quiet)
        assert list(Path(tmp).rglob("*")) == [], "files were written after a failure"


# ---------------------------------------------------------------- cross-check logic

def test_crosscheck_rounding():
    latest = {"gross_debt": Decimal("971447"), "net_debt": Decimal("549969"),
              "gross_debt_pct_gdp": Decimal("33.2"), "net_debt_pct_gdp": Decimal("18.8")}
    p1 = {"gross_b": Decimal("971.4"), "gross_pct": Decimal("33.2"), "net_b": Decimal("550.0"), "net_pct": Decimal("18.8")}
    assert all(r[3] for r in cd.crosscheck(latest, p1))
    p1_bad = dict(p1, net_b=Decimal("549.9"))
    res = cd.crosscheck(latest, p1_bad)
    assert [r[3] for r in res] == [True, True, False, True]


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
