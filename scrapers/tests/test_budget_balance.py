#!/usr/bin/env python3
"""Tests for scrapers/budget_balance.py. Plain asserts; run with pytest or directly.

Needs no network. The small Word files are built here, in the shape of Table B.1 of the
Final Budget Outcome (a 12-column table in two pieces, the second '(continued)') and of the
overview table in Part 1. The real 2024-25 Appendix B kept in fixtures/ is also read once.
"""
import io
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import budget_balance as bb  # noqa: E402
import docx  # noqa: E402
from docx.table import _Cell  # noqa: E402

REAL_2024_25 = HERE / "fixtures" / "fbo-2024-25-appendix-b.docx"
quiet = lambda msg: None  # noqa: E731
CAPTION = "Table B.1: Australian Government general government sector receipts, payments, net Future Fund earnings and underlying cash balance(a)"


def raises(fn, *args):
    try:
        fn(*args)
    except bb.ScrapeError as e:
        return str(e)
    raise AssertionError(f"expected ScrapeError from {fn.__name__}")


def ucb_for(start):
    """A made-up underlying cash balance, $m: negative in odd years, positive in even years.
    2025-26 is set to the real published figure so that it agrees with the made-up Part 1 file."""
    if start == 2025:
        return -22254
    v = 900 + (start - 1970) * 400
    return -v if start % 2 else v


def pct_for(start):
    if start == 2025:
        return Decimal("-0.8")
    v = Decimal(900 + (start - 1970) * 400) / Decimal(10000)
    v = v.quantize(Decimal("0.1"))
    return -v if start % 2 else v


def fmt_m(v):
    return f"{v:,}" if v >= 0 else f"-{-v:,}"


def make_table(document, data_rows):
    """A 12-column Table B.1 piece: the real header layout, then data rows (lists of 12 strings)."""
    t = document.add_table(rows=5 + len(data_rows), cols=12)
    h = [
        {8: "Net Future", 10: "Underlying"},
        {8: "Fund", 10: "cash"},
        {1: "Receipts(b)", 4: "Payments(c)", 8: "earnings", 10: "balance(d)"},
        {2: "Per cent", 5: "Per cent real", 6: "Per cent", 11: "Per cent"},
        {1: "$m", 2: "of GDP", 4: "$m", 5: "growth(e)", 6: "of GDP", 8: "$m", 10: "$m", 11: "of GDP"},
    ]
    for r, cells in enumerate(h):
        for c, text in cells.items():
            t.cell(r, c).text = text
    t.cell(2, 1).merge(t.cell(2, 2))
    t.cell(2, 4).merge(t.cell(2, 6))
    for r in range(3):
        t.cell(r, 10).merge(t.cell(r, 11))
    for i, row in enumerate(data_rows):
        for c, text in enumerate(row):
            t.cell(5 + i, c).text = text
    return t


def data_row(start):
    label = f"{start}-{(start + 1) % 100:02d}"
    row = [label, "100,000", "20.0", "", "100,000", "1.0", "20.0", "", "0", "", fmt_m(ucb_for(start)), f"{pct_for(start)}"]
    return row


_cache = {}


def appendix_docx(mutate=None, last=2025):
    if mutate is None and last in _cache:  # building a Word file is slow; the plain one never changes
        return _cache[last]
    out = _appendix_docx(mutate, last)
    if mutate is None:
        _cache[last] = out
    return out


def _appendix_docx(mutate, last):
    """Table B.1 in two pieces: 1970-71 to 2009-10 and 2010-11 to `last`."""
    document = docx.Document()
    document.add_paragraph(CAPTION)
    make_table(document, [data_row(y) for y in range(1970, 2010)])
    document.add_paragraph(CAPTION + " (continued)")
    make_table(document, [data_row(y) for y in range(2010, last + 1)])
    if mutate:
        mutate(document)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def part1_docx(ucb_b="-22.3", pct="-0.8"):
    document = docx.Document()
    document.add_paragraph("Table 1.1: Overview of key Australian Government general government sector budget aggregates")
    t = document.add_table(rows=5, cols=2)
    for r, text in enumerate(["2025-26", "Outcome", "$b"]):
        t.cell(r, 1).text = text
    t.cell(3, 0).text = "Underlying cash balance(a)"
    t.cell(3, 1).text = ucb_b
    t.cell(4, 0).text = "Per cent of GDP"
    t.cell(4, 1).text = pct
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def fetcher_for(appendix, part1):
    return lambda url: appendix if "appendix_b" in url else part1


def find_row(document, label):
    for table in document.tables:
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


# ---------------------------------------------------------------- reading and signs

def test_reads_every_year_from_both_pieces_and_keeps_the_sign():
    info, parsed = bb.parse_table_b1(appendix_docx(), "2025-26", quiet)
    assert info["table"] == "B.1" and info["pieces"] == 2
    assert len(parsed) == 56 and min(parsed) == 1970 and max(parsed) == 2025
    assert parsed[1970]["ucb"] == Decimal(ucb_for(1970))
    assert parsed[1971]["ucb"] < 0 and parsed[1971]["ucb_pct_gdp"] < 0      # deficit stays a deficit
    assert parsed[1972]["ucb"] > 0 and parsed[1972]["ucb_pct_gdp"] > 0      # surplus stays a surplus
    assert parsed[2025]["period"] == "2025-26" and parsed[2025]["ucb"] == Decimal(ucb_for(2025)) < 0
    rows = bb.build_rows(parsed)
    assert len(rows) == 112
    by = {(r[2], r[1]): r[4] for r in rows}
    assert by[("ucb", "2025-26")] == str(ucb_for(2025)) and by[("ucb", "1971-72")] == str(ucb_for(1971))
    assert by[("ucb_pct_gdp", "2025-26")] == f"{pct_for(2025)}"
    assert rows[0][:3] == ["1971-06-30", "1970-71", "ucb"] and rows[0][5] == "aud_million"
    assert {r[5] for r in rows if r[2] == "ucb_pct_gdp"} == {"pct_gdp"}


def test_minus_sign_variants_are_read_as_negative():
    def edit(d):
        table, tr = find_row(d, "1972-73")  # an even year: positive by default
        set_cell(table, tr, 10, "−1,000")
        set_cell(table, tr, 11, "−0.4")
    _, parsed = bb.parse_table_b1(appendix_docx(edit), "2025-26", quiet)
    assert parsed[1972]["ucb"] == Decimal("-1000") and parsed[1972]["ucb_pct_gdp"] == Decimal("-0.4")


def test_real_2024_25_file_reads_and_has_the_surplus_in_2022_23():
    info, parsed = bb.parse_table_b1(str(REAL_2024_25), "2024-25", quiet)
    assert len(parsed) == 55 and info["pieces"] == 2
    assert parsed[1970]["ucb"] == Decimal("901")
    assert parsed[2022]["period"] == "2022-23" and parsed[2022]["ucb"] == Decimal("22064") and parsed[2022]["ucb_pct_gdp"] == Decimal("0.9")
    assert parsed[2021]["ucb"] < 0


# ---------------------------------------------------------------- refusals

def test_header_layout_change_is_refused():
    # 1. a heading is renamed
    def edit_name(d):
        for table in d.tables:
            for tr in table._tbl.tr_lst:
                for tc in tr.tc_lst:
                    cell = _Cell(tc, table)
                    if cell.text == "Underlying":
                        cell.paragraphs[0].runs[0].text = "Headline"
    msg = raises(bb.parse_table_b1, appendix_docx(edit_name), "2025-26", quiet)
    assert "header layout" in msg or "expected exactly one column" in msg
    # 2. the unit under the column changes from $m to $b: refused as a layout change
    def edit_unit(d):
        table = d.tables[1]
        _Cell(table._tbl.tr_lst[4].tc_lst[10], table).paragraphs[0].runs[0].text = "$b"
    msg = raises(bb.parse_table_b1, appendix_docx(edit_unit), "2025-26", quiet)
    assert "header layout" in msg and "piece 2" in msg
    # 3. a column is added (thirteen columns): refused
    def add_column(d):
        table = d.tables[0]
        table.add_column(docx.shared.Cm(2))
    msg = raises(bb.parse_table_b1, appendix_docx(add_column), "2025-26", quiet)
    assert "header layout" in msg or "different number of columns" in msg


def test_missing_year_is_refused():
    def edit(d):
        table, tr = find_row(d, "1990-91")
        tr.getparent().remove(tr)
    msg = raises(bb.parse_table_b1, appendix_docx(edit), "2025-26", quiet)
    assert "missing years" in msg and "1990-91" in msg


def test_missing_latest_year_is_refused():
    msg = raises(bb.parse_table_b1, appendix_docx(last=2024), "2025-26", quiet)
    assert "last year" in msg and "2024-25" in msg


def test_unreadable_value_is_refused():
    def edit(d):
        table, tr = find_row(d, "1990-91")
        set_cell(table, tr, 10, "n/a")
    msg = raises(bb.parse_table_b1, appendix_docx(edit), "2025-26", quiet)
    assert "1990-91" in msg


def test_value_outside_the_plausible_range_is_refused():
    def edit(d):
        table, tr = find_row(d, "1990-91")
        set_cell(table, tr, 10, "-3,000,000")  # a slipped digit
    _, parsed = bb.parse_table_b1(appendix_docx(edit), "2025-26", quiet)
    msg = raises(bb.build_rows, parsed)
    assert "plausible range" in msg and "1990-91" in msg


def test_table_not_found_is_refused():
    def edit(d):
        for p in d.paragraphs:
            p.runs[0].text = p.runs[0].text.replace("net Future Fund earnings", "something else")
    msg = raises(bb.parse_table_b1, appendix_docx(edit), "2025-26", quiet)
    assert "no table with a caption" in msg


# ---------------------------------------------------------------- Part 1 cross-check and writing

def test_part1_agreement_writes_files_and_a_second_run_is_identical():
    appendix, part1 = appendix_docx(), part1_docx()
    with tempfile.TemporaryDirectory() as tmp:
        out = bb.run("2025-26", tmp, fetcher_for(appendix, part1), quiet)
        assert all(r[3] for r in out["crosscheck"])
        m = Path(tmp) / "metrics" / "budget-balance"
        first = {p.name: p.read_bytes() for p in [m / "data.csv", m / "sources" / "manifest.json",
                                                   m / "sources" / "fbo-2025-26-appendix-b.docx", m / "sources" / "fbo-2025-26-part-1.docx"]}
        assert first["fbo-2025-26-appendix-b.docx"] == appendix and first["fbo-2025-26-part-1.docx"] == part1  # byte for byte
        assert len(first["data.csv"].decode().splitlines()) == 113
        bb.run("2025-26", tmp, fetcher_for(appendix, part1), quiet)
        second = {p.name: p.read_bytes() for p in [m / "data.csv", m / "sources" / "manifest.json",
                                                    m / "sources" / "fbo-2025-26-appendix-b.docx", m / "sources" / "fbo-2025-26-part-1.docx"]}
        assert first == second


def test_part1_disagreement_is_refused_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        # Appendix B says -22,254 (rounds to -22.3); Part 1 says -22.4.
        msg = raises(bb.run, "2025-26", tmp, fetcher_for(appendix_docx(), part1_docx(ucb_b="-22.4")), quiet)
        assert "Part 1" in msg and "-22.4" in msg
        assert list(Path(tmp).rglob("*")) == [], "files were written after a failure"
    with tempfile.TemporaryDirectory() as tmp:
        # A sign flip in Part 1 is a disagreement too.
        raises(bb.run, "2025-26", tmp, fetcher_for(appendix_docx(), part1_docx(ucb_b="22.3")), quiet)
        assert list(Path(tmp).rglob("*")) == []
    with tempfile.TemporaryDirectory() as tmp:
        # And so is the share of GDP.
        raises(bb.run, "2025-26", tmp, fetcher_for(appendix_docx(), part1_docx(pct="-0.9")), quiet)
        assert list(Path(tmp).rglob("*")) == []


def test_part1_without_the_row_is_refused():
    document = docx.Document()
    document.add_paragraph("Table 1.1: Overview of key Australian Government general government sector budget aggregates")
    t = document.add_table(rows=5, cols=2)
    for r, text in enumerate(["2025-26", "Outcome", "$b"]):
        t.cell(r, 1).text = text
    t.cell(3, 0).text = "Headline cash balance"
    t.cell(3, 1).text = "-22.3"
    buf = io.BytesIO()
    document.save(buf)
    msg = raises(bb.parse_part1_ucb, buf.getvalue(), "2025-26")
    assert "Underlying cash balance" in msg


def test_a_failed_download_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        raises(bb.run, "2025-26", tmp, fetcher_for(appendix_docx(), b"not a word file"), quiet)
        assert list(Path(tmp).rglob("*")) == []


def test_crosscheck_rounding():
    latest = {"ucb": Decimal("-22254"), "ucb_pct_gdp": Decimal("-0.8")}
    assert all(r[3] for r in bb.crosscheck(latest, {"ucb_b": Decimal("-22.3"), "ucb_pct": Decimal("-0.8")}))
    assert [r[3] for r in bb.crosscheck(latest, {"ucb_b": Decimal("-22.2"), "ucb_pct": Decimal("-0.8")})] == [False, True]


def test_picks_up_a_new_budget_year_from_the_debt_scrapers_address():
    import commonwealth_debt as cd
    assert bb.BASE_URL is cd.BASE_URL and bb.DEFAULT_YEAR == cd.DEFAULT_YEAR
    def part1_for(year):
        document = docx.Document()
        document.add_paragraph("Table 1.1: Overview of key Australian Government general government sector budget aggregates")
        t = document.add_table(rows=5, cols=2)
        for r, text in enumerate([year, "Outcome", "$b"]):
            t.cell(r, 1).text = text
        t.cell(3, 0).text = "Underlying cash balance"
        t.cell(3, 1).text = fmt_b(ucb_for(2026))
        t.cell(4, 0).text = "Per cent of GDP"
        t.cell(4, 1).text = f"{pct_for(2026)}"
        buf = io.BytesIO()
        document.save(buf)
        return buf.getvalue()
    def fmt_b(v):
        return str((Decimal(v) / 1000).quantize(Decimal("0.1")))
    with tempfile.TemporaryDirectory() as tmp:
        bb.run("2026-27", tmp, fetcher_for(appendix_docx(last=2026), part1_for("2026-27")), quiet)
        rows = (Path(tmp) / "metrics" / "budget-balance" / "data.csv").read_text().splitlines()
        assert len(rows) == 115 and rows[-1].split(",")[1] == "2026-27"


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"pass {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e!r}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
