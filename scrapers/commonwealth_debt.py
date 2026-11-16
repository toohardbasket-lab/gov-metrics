#!/usr/bin/env python3
"""Commonwealth debt scraper.

Downloads two Word files from Treasury's Final Budget Outcome (Appendix B and
Part 1), reads the debt tables in code, checks them, and writes
metrics/commonwealth-debt/data.csv.

Run from anywhere:  python3 scrapers/commonwealth_debt.py [budget-year-folder]
The folder defaults to 2025-26 (the year in the archive.budget.gov.au address).

What it does, in order:
  1. Downloads both files into memory.
  2. Reads the net debt table and the total AGS on issue table from Appendix B.
     Tables are found by their caption text, never by position.
  3. Checks everything (see the list in check_and_build below and the README).
  4. Only if every check passes: saves the two files unchanged under
     metrics/commonwealth-debt/sources/, records them in sources/manifest.json,
     and writes data.csv. If any check fails nothing is written and the exit
     code is 1.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import docx
import requests
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YEAR = "2025-26"
FIRST_START_YEAR = 1970  # the tables start at 1970-71
BASE_URL = "https://archive.budget.gov.au/{year}/fbo/download/{name}.docx"
APPENDIX_B = "06_appendix_b"
PART_1 = "01_part_1"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) gov-metrics-scraper"

# (series id, unit, plausible range). Anything outside the range stops the run.
SERIES = [
    ("gross_debt", "aud_million", (1_000, 3_000_000)),
    ("net_debt", "aud_million", (-100_000, 3_000_000)),
    ("gross_debt_pct_gdp", "pct_gdp", (0, 100)),
    ("net_debt_pct_gdp", "pct_gdp", (-10, 100)),
]
HEADER = ["date", "period", "series", "jurisdiction", "value", "unit", "status"]


class ScrapeError(Exception):
    """Something is wrong with the source or the data. Nothing gets written."""


# ---------------------------------------------------------------- text and numbers

# Every kind of dash and minus Treasury (or Word) might use for a negative sign:
# hyphen-minus, hyphen, non-breaking hyphen, figure dash, en dash, em dash,
# horizontal bar, minus sign, small hyphen-minus, full-width hyphen-minus.
DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
DASH_TABLE = {ord(c): "-" for c in DASHES}
SPACES = "     　\t\r\n"
SPACE_TABLE = {ord(c): " " for c in SPACES}
INVISIBLE_TABLE = {ord(c): None for c in "​‌‍⁠﻿­"}
# A footnote marker such as (a) or (e), lower-case letters in brackets.
FOOTNOTE = re.compile(r"\(\s*[a-z]{1,2}\s*\)")


def clean(text: str) -> str:
    """Plain text with odd spaces and invisible characters removed, single spaces."""
    t = text.translate(INVISIBLE_TABLE).translate(SPACE_TABLE)
    return re.sub(r" +", " ", t).strip()


def parse_number(text: str) -> Decimal:
    """Turn a table cell such as '-1,851', '1,234(e)' or '−0.5' into a Decimal.

    Footnote markers and thousands separators are removed and every dash variant
    is read as a minus sign. A lone dash (Treasury's mark for nil), 'na', an empty
    cell, or anything else that is not a plain number raises ScrapeError, because
    guessing here would put a wrong figure on the page.
    """
    s = clean(text)
    s = FOOTNOTE.sub("", s).replace(" ", "")
    s = s.translate(DASH_TABLE)
    if s in ("", "-", "na", "n.a.", "..", "nm", "np"):
        raise ScrapeError(f"not a number: {text!r} (empty, nil or not available)")
    if not re.fullmatch(r"-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?", s):
        raise ScrapeError(f"not a number: {text!r}")
    return Decimal(s.replace(",", ""))


YEAR_LABEL = re.compile(r"^(\d{4}) ?- ?(\d{2})(.*)$")
PROJECTION_WORDS = re.compile(r"estimate|forecast|projection|budget|forward", re.I)


def parse_year_label(text: str):
    """'1970-71', '2024-25 (a)', '2010–11' -> (start_year, '2010-11', annotation).

    Returns None if the text is not a financial-year label. The annotation is
    whatever follows the year once footnote markers are removed (usually empty).
    Raises ScrapeError if the two halves do not make one financial year.
    """
    s = clean(text).translate(DASH_TABLE)
    m = YEAR_LABEL.match(s)
    if not m:
        return None
    start, end2, rest = int(m.group(1)), int(m.group(2)), m.group(3)
    if end2 != (start + 1) % 100:
        raise ScrapeError(f"year label does not make a financial year: {text!r}")
    marker_free = FOOTNOTE.sub("", rest).strip()
    return start, f"{start}-{end2:02d}", marker_free, bool(FOOTNOTE.search(rest))


# ---------------------------------------------------------------- reading the Word file

def blocks(document):
    """Yields ('p', text) for each top-level paragraph and ('t', Table) for each table."""
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield "p", Paragraph(child, document).text
        elif tag == "tbl":
            yield "t", Table(child, document)


CAPTION = re.compile(r"^Table ([A-Z]\.\d+|\d+\.\d+) ?: ?(.*)$")


def find_tables(document, description_re: str):
    """Finds the tables whose caption description matches description_re.

    The caption is the last non-empty paragraph before the table, e.g.
    'Table B.4: Australian Government general government sector net debt ...'.
    Returns (table_number, [Table, ...]) with the first table plus any pieces
    marked '(continued)'. Raises ScrapeError if there is no match, if the match
    is not found under one table number, or if the pieces are not in the
    expected first-then-continued order.
    """
    wanted = re.compile(description_re)
    last = ""
    found = []  # (number, is_continued, Table)
    for kind, item in blocks(document):
        if kind == "p":
            if clean(item):
                last = item
            continue
        cap = CAPTION.match(FOOTNOTE.sub("", clean(last)).strip())
        if not cap:
            continue
        number, desc = cap.group(1), cap.group(2).strip()
        continued = bool(re.search(r"\(continued\)\s*$", desc))
        desc = re.sub(r"\s*\(continued\)\s*$", "", desc).strip()
        if wanted.search(desc):
            found.append((number, continued, item))
    if not found:
        raise ScrapeError(f"no table with a caption matching /{description_re}/ was found")
    numbers = {n for n, _, _ in found}
    if len(numbers) != 1:
        raise ScrapeError(f"caption /{description_re}/ matched more than one table number: {sorted(numbers)}")
    if found[0][1]:
        raise ScrapeError(f"Table {found[0][0]}: the first piece is marked (continued)")
    if any(not c for _, c, _ in found[1:]):
        raise ScrapeError(f"Table {found[0][0]}: a later piece is not marked (continued), so the same caption appears twice")
    return found[0][0], [t for _, _, t in found]


def grid_rows(table):
    """Rows as lists of (first_column, span, text), using the real grid so that
    merged header cells line up with the data columns beneath them."""
    rows = []
    for tr in table._tbl.tr_lst:
        col = getattr(tr, "grid_before", 0) or 0
        cells = []
        for tc in tr.tc_lst:
            span = tc.grid_span or 1
            cells.append((col, span, clean(_Cell(tc, table).text)))
            col += span
        rows.append(cells)
    return rows


def split_header(rows):
    """Header rows are the leading rows whose first cell is empty."""
    n = 0
    while n < len(rows) and (not rows[n] or rows[n][0][2] == ""):
        n += 1
    if n == 0 or n == len(rows):
        raise ScrapeError("table has no recognisable header rows")
    return rows[:n], rows[n:]


def column_headings(header_rows):
    """For each grid column, the list of heading texts above it, top to bottom,
    with footnote markers removed."""
    parts = {}
    for row in header_rows:
        for start, span, text in row:
            text = FOOTNOTE.sub("", text).strip()
            text = re.sub(r" +", " ", text)
            if not text:
                continue
            for c in range(start, start + span):
                parts.setdefault(c, []).append(text)
    return parts


def pick_column(parts, test, what):
    """The one grid column whose headings satisfy test(joined_lower, parts_lower)."""
    hits = []
    for col, p in parts.items():
        low = [x.lower() for x in p]
        if col > 0 and test(" ".join(low), low):
            hits.append(col)
    if len(hits) != 1:
        shown = {c: " | ".join(p) for c, p in sorted(parts.items())}
        raise ScrapeError(f"expected exactly one column for {what}, found {len(hits)}. Headings: {shown}")
    return hits[0]


def cell_at(row, col):
    for start, span, text in row:
        if start <= col < start + span:
            return text
    raise ScrapeError(f"row has no cell in column {col}")


# ---------------------------------------------------------------- Appendix B

# (table caption description, then the columns to take: key -> test on headings)
APPENDIX_TABLES = {
    "net_debt": {
        "caption": r"^Australian Government general government sector net debt and net interest payments$",
        "expect_number": "B.4",
        "columns": {
            "net_debt": (lambda j, p: "net debt" in j and "$m" in p, "net debt, $m"),
            "net_debt_pct_gdp": (lambda j, p: "net debt" in j and "per cent of gdp" in j, "net debt, per cent of GDP"),
        },
    },
    "gross_debt": {
        "caption": r"^Australian Government general government sector face value of Australian Government Securities \(AGS\) on issue and interest paid$",
        "expect_number": "B.5",
        "columns": {
            "gross_debt": (lambda j, p: "total ags on issue" in j and "end of year" in j and "$m" in p, "total AGS on issue, end of year, $m"),
            "gross_debt_pct_gdp": (lambda j, p: "total ags on issue" in j and "per cent of gdp" in j, "total AGS on issue, per cent of GDP"),
        },
    },
}


def parse_debt_table(document, spec, budget_year_start, log):
    """Reads one Appendix B table (all its pieces).

    Returns (info, {start_year: {"period": '1970-71', series_id: Decimal, ...}}).
    """
    number, tables = find_tables(document, spec["caption"])
    if number != spec["expect_number"]:
        raise ScrapeError(f"expected Table {spec['expect_number']} but the file calls it Table {number}. "
                          f"Check the table is the right one, then update expect_number here and the "
                          f"table references in metric.yml.")
    info = {"table": number, "pieces": len(tables), "columns": {}}
    out = {}
    for t_index, table in enumerate(tables):
        header_rows, data_rows = split_header(grid_rows(table))
        parts = column_headings(header_rows)
        width = max(c for c in parts) + 1
        cols = {}
        for key, (test, what) in spec["columns"].items():
            cols[key] = pick_column(parts, test, what)
            info["columns"][key] = " | ".join(parts[cols[key]])
        for row in data_rows:
            label = row[0][2] if row else ""
            if label == "":
                continue
            yl = parse_year_label(label)
            if yl is None:
                raise ScrapeError(f"Table {number}: unrecognised row label {label!r}")
            start, period, annotation, had_marker = yl
            if row[-1][0] + row[-1][1] != width:
                raise ScrapeError(f"Table {number}, {period}: row has a different number of columns from the header")
            if had_marker:
                log(f"Table {number}, {period}: footnote marker on the year label ignored ({label!r})")
            if annotation and PROJECTION_WORDS.search(annotation):
                log(f"Table {number}: skipped {period}, labelled as an estimate or projection ({label!r})")
                continue
            if annotation:
                raise ScrapeError(f"Table {number}, {period}: unexpected text after the year: {annotation!r}")
            if start > budget_year_start:
                log(f"Table {number}: skipped {period}, later than the budget outcome year, so a projection")
                continue
            if start in out:
                raise ScrapeError(f"Table {number}: {period} appears twice")
            rec = {"period": period}
            for key, col in cols.items():
                raw = cell_at(row, col)
                try:
                    rec[key] = parse_number(raw)
                except ScrapeError as e:
                    raise ScrapeError(f"Table {number}, {period}, {key}: {e}") from None
            out[start] = rec
    return info, out


def check_sequence(rows, table, budget_year_start):
    years = sorted(rows)
    if not years:
        raise ScrapeError(f"Table {table}: no year rows found")
    if years[0] != FIRST_START_YEAR:
        raise ScrapeError(f"Table {table}: first year is {years[0]}-{(years[0] + 1) % 100:02d}, expected {FIRST_START_YEAR}-71")
    missing = [y for y in range(years[0], years[-1] + 1) if y not in rows]
    if missing:
        raise ScrapeError(f"Table {table}: missing years {[f'{y}-{(y + 1) % 100:02d}' for y in missing]}")
    if years[-1] != budget_year_start:
        raise ScrapeError(f"Table {table}: last year is {years[-1]}-{(years[-1] + 1) % 100:02d}, expected {budget_year_start}-{(budget_year_start + 1) % 100:02d}")


def parse_appendix_b(source, budget_year, log=print):
    """Parses Appendix B (a path or bytes). Returns (info, {start_year: record}).

    Each record has 'period' and the four series as Decimals. Raises ScrapeError
    if either table is missing, has a gap, a duplicate or an unreadable value, or
    if the two tables do not cover the same years.
    """
    document = open_docx(source)
    start_year = int(budget_year[:4])
    info, merged, per_table = {}, {}, {}
    for name, spec in APPENDIX_TABLES.items():
        tinfo, rows = parse_debt_table(document, spec, start_year, log)
        check_sequence(rows, tinfo["table"], start_year)
        info[name], per_table[name] = tinfo, rows
    a, b = per_table["net_debt"], per_table["gross_debt"]
    if set(a) != set(b):
        raise ScrapeError(f"the two tables cover different years: only in net debt table {sorted(set(a) - set(b))}, "
                          f"only in AGS table {sorted(set(b) - set(a))}")
    for y in sorted(a):
        if a[y]["period"] != b[y]["period"]:
            raise ScrapeError(f"period label differs between tables for {y}: {a[y]['period']} and {b[y]['period']}")
        merged[y] = {**a[y], **b[y]}
    return info, merged


def open_docx(source):
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        return docx.Document(source)
    except Exception as e:  # not a Word file, damaged, etc.
        raise ScrapeError(f"the file could not be opened as a Word document: {e}") from None


# ---------------------------------------------------------------- Part 1 cross-check

def parse_part1_overview(source, budget_year, log=print):
    """Reads gross and net debt for the outcome year from the overview table
    ('Table 1.1: Overview of key ... budget aggregates').

    Returns {'table': '1.1', 'gross_b': Decimal, 'gross_pct': Decimal,
             'net_b': Decimal, 'net_pct': Decimal, 'column': 'heading text'}.
    """
    document = open_docx(source)
    number, tables = find_tables(document, r"^Overview of key Australian Government general government sector budget aggregates$")
    if len(tables) != 1:
        raise ScrapeError(f"Part 1 overview table: expected one piece, found {len(tables)}")
    header_rows, data_rows = split_header(grid_rows(tables[0]))
    parts = column_headings(header_rows)
    col = pick_column(parts, lambda j, p: budget_year in j and "outcome" in j and "$b" in p, f"{budget_year} outcome, $b")

    def label_of(row):
        return FOOTNOTE.sub("", row[0][2]).strip()

    def find_pair(name):
        idx = [i for i, r in enumerate(data_rows) if label_of(r) == name]
        if len(idx) != 1:
            raise ScrapeError(f"Part 1 Table {number}: expected one row labelled {name!r}, found {len(idx)}")
        i = idx[0]
        if i + 1 >= len(data_rows) or label_of(data_rows[i + 1]) != "Per cent of GDP":
            raise ScrapeError(f"Part 1 Table {number}: the row after {name!r} is not 'Per cent of GDP'")
        return (parse_number(cell_at(data_rows[i], col)), parse_number(cell_at(data_rows[i + 1], col)))

    gross_b, gross_pct = find_pair("Gross debt")
    net_b, net_pct = find_pair("Net debt")
    return {"table": number, "column": " | ".join(parts[col]),
            "gross_b": gross_b, "gross_pct": gross_pct, "net_b": net_b, "net_pct": net_pct}


def one_decimal(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def crosscheck(latest, p1):
    """Compares the latest-year Appendix B figures with the Part 1 overview.
    Returns a list of (name, appendix_value, part1_value, matches)."""
    rows = [
        ("gross debt, $b", one_decimal(latest["gross_debt"] / 1000), p1["gross_b"]),
        ("gross debt, % of GDP", one_decimal(latest["gross_debt_pct_gdp"]), p1["gross_pct"]),
        ("net debt, $b", one_decimal(latest["net_debt"] / 1000), p1["net_b"]),
        ("net debt, % of GDP", one_decimal(latest["net_debt_pct_gdp"]), p1["net_pct"]),
    ]
    return [(n, a, b, a == b) for n, a, b in rows]


# ---------------------------------------------------------------- checks and output

def format_value(series, unit, d: Decimal) -> str:
    if unit == "aud_million":
        if d != d.to_integral_value():
            raise ScrapeError(f"{series}: expected a whole number of $m, got {d}")
        return str(int(d))
    if d != one_decimal(d):
        raise ScrapeError(f"{series}: expected one decimal place, got {d}")
    d = one_decimal(d)
    if d == 0:
        d = Decimal("0.0")
    return f"{d:.1f}"


def build_rows(parsed):
    """The long-format rows for data.csv, in series order then year order."""
    out = []
    for series, unit, (lo, hi) in SERIES:
        for y in sorted(parsed):
            rec = parsed[y]
            v = rec[series]
            if not (lo <= v <= hi):
                raise ScrapeError(f"{series} {rec['period']}: {v} is outside the plausible range {lo} to {hi}")
            out.append([f"{y + 1}-06-30", rec["period"], series, "Commonwealth", format_value(series, unit, v), unit, "actual"])
    return out


def existing_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def fetch(url: str):
    """Downloads a file. Returns the bytes. Retries network errors, not bad answers."""
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            last = e
            time.sleep(2)
            continue
        if r.status_code != 200:
            raise ScrapeError(f"{url} answered HTTP {r.status_code}")
        if not r.content.startswith(b"PK"):
            raise ScrapeError(f"{url} did not return a Word file (it does not start like a zip file)")
        return r.content
    raise ScrapeError(f"{url} could not be downloaded: {last}")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run(budget_year, root=ROOT, fetcher=fetch, log=print):
    if not re.fullmatch(r"\d{4}-\d{2}", budget_year):
        raise ScrapeError(f"budget year folder must look like 2025-26, got {budget_year!r}")
    start = int(budget_year[:4])
    if int(budget_year[5:]) != (start + 1) % 100:
        raise ScrapeError(f"{budget_year} is not a financial year")
    metric_dir = Path(root) / "metrics" / "commonwealth-debt"
    sources = metric_dir / "sources"

    files = {}  # file name -> (url, bytes)
    for part, label in ((APPENDIX_B, "appendix-b"), (PART_1, "part-1")):
        url = BASE_URL.format(year=budget_year, name=part)
        log(f"Downloading {url}")
        files[f"fbo-{budget_year}-{label}.docx"] = (url, fetcher(url))
    retrieved = datetime.now(timezone.utc).date().isoformat()
    appendix_bytes = files[f"fbo-{budget_year}-appendix-b.docx"][1]
    part1_bytes = files[f"fbo-{budget_year}-part-1.docx"][1]

    skipped = []
    base_log = log

    def log(msg):  # keeps a count of skipped rows and passes everything on
        if "skipped" in msg:
            skipped.append(msg)
        base_log(msg)

    info, parsed = parse_appendix_b(appendix_bytes, budget_year, log)
    for name in ("net_debt", "gross_debt"):
        t = info[name]
        log(f"Found Table {t['table']} in {t['pieces']} piece(s) (the first plus any '(continued)').")
        for key, heading in t["columns"].items():
            log(f"  {key}: column headings '{heading}'")
    years = sorted(parsed)
    log(f"Years: {parsed[years[0]]['period']} to {parsed[years[-1]]['period']} ({len(years)} years, no gaps, no duplicates)")
    log(f"Estimate or projection rows skipped: {len(skipped)}" + ("" if skipped else " (none found in either table)"))

    rows = build_rows(parsed)

    p1 = parse_part1_overview(part1_bytes, budget_year, log)
    log(f"Part 1 Table {p1['table']}, column '{p1['column']}'")
    results = crosscheck(parsed[years[-1]], p1)
    for name, a, b, ok in results:
        log(f"  cross-check {name}: Appendix B {a}  Part 1 {b}  {'match' if ok else 'MISMATCH'}")
    bad = [r for r in results if not r[3]]
    if bad:
        raise ScrapeError("the latest year does not match the Part 1 overview table: "
                          + "; ".join(f"{n}: Appendix B {a}, Part 1 {b}" for n, a, b, _ in bad))

    old = existing_row_count(metric_dir / "data.csv")
    if len(rows) < old:
        raise ScrapeError(f"the new data has {len(rows)} rows but the current data.csv has {old}. The row count must not fall.")

    # Everything has passed. Now, and only now, write files.
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name, (url, content) in files.items():
        write_atomic(sources / name, content)
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": sha256(content), "bytes": len(content)}
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(rows)
    write_atomic(metric_dir / "data.csv", buf.getvalue().encode("utf-8"))
    log(f"Wrote {len(rows)} rows to metrics/commonwealth-debt/data.csv, saved {len(files)} source files and the manifest.")
    return {"info": info, "parsed": parsed, "part1": p1, "crosscheck": results, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download and parse Commonwealth debt from the Final Budget Outcome.")
    ap.add_argument("year", nargs="?", default=DEFAULT_YEAR, help="budget year folder, e.g. 2025-26 (default)")
    ap.add_argument("--root", default=str(ROOT), help="project folder to write into (default: this project)")
    args = ap.parse_args(argv)
    try:
        run(args.year, root=args.root)
    except ScrapeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
