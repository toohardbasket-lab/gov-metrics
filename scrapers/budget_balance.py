#!/usr/bin/env python3
"""Budget balance scraper (the underlying cash balance).

Reads Table B.1 of Treasury's Final Budget Outcome, Appendix B (the same Word file
the debt scraper reads, found in the same way), checks it, and writes
metrics/budget-balance/data.csv.

Run from anywhere:  python3 scrapers/budget_balance.py [budget-year-folder]
The folder defaults to the debt scraper's (2025-26), so a new Final Budget Outcome is
picked up in the same way as for the debt page.

What it does, in order:
  1. Downloads Appendix B and Part 1 into memory (the addresses come from the debt scraper).
  2. Finds Table B.1 by its caption, refuses unless its header layout is exactly the expected
     twelve columns, and reads the underlying cash balance ($m and per cent of GDP) from
     every piece of the table ('(continued)').
  3. Checks every year is there, every value is a number inside its plausible range, and
     that the latest year equals the underlying cash balance row of the Part 1 overview table.
  4. Only if every check passes: saves the two files unchanged under
     metrics/budget-balance/sources/, records them in sources/manifest.json, and writes
     data.csv. If any check fails nothing is written and the exit code is 1.

Negative figures are deficits. The sign is kept as published.
"""
import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# The Word-reading helpers and the file addresses come from the debt scraper, so the two
# pages find and read the Final Budget Outcome in exactly the same way.
from commonwealth_debt import (  # noqa: F401
    APPENDIX_B, BASE_URL, DEFAULT_YEAR, FOOTNOTE, HEADER, PART_1, ROOT, ScrapeError,
    cell_at, check_sequence, column_headings, existing_row_count, fetch, find_tables, format_value,
    grid_rows, one_decimal, open_docx, parse_debt_table, parse_number, pick_column, sha256,
    split_header, write_atomic,
)

# (series id, unit, plausible range). Anything outside the range stops the run.
SERIES = [
    ("ucb", "aud_million", (-300_000, 100_000)),
    ("ucb_pct_gdp", "pct_gdp", (-15, 10)),
]

TABLE_SPEC = {
    "caption": r"^Australian Government general government sector receipts, payments, net Future Fund earnings and underlying cash balance$",
    "expect_number": "B.1",
    "columns": {
        "ucb": (lambda j, p: "underlying cash balance" in j and "$m" in p, "underlying cash balance, $m"),
        "ucb_pct_gdp": (lambda j, p: "underlying cash balance" in j and "per cent of gdp" in j, "underlying cash balance, per cent of GDP"),
    },
}

# The header of every piece of Table B.1, column by column (column 0 is the year label; columns 3 and 7 are
# blank spacers). If Treasury moves, adds, removes or renames a column the run stops, because the figures
# could then be read from the wrong column.
EXPECTED_WIDTH = 12
EXPECTED_HEADINGS = {
    1: ["receipts", "$m"],
    2: ["receipts", "per cent", "of gdp"],
    4: ["payments", "$m"],
    5: ["payments", "per cent real", "growth"],
    6: ["payments", "per cent", "of gdp"],
    8: ["net future", "fund", "earnings", "$m"],
    10: ["underlying", "cash", "balance", "$m"],
    11: ["underlying", "cash", "balance", "per cent", "of gdp"],
}


def check_layout(document):
    """Refuses unless every piece of Table B.1 has exactly the expected header layout."""
    number, pieces = find_tables(document, TABLE_SPEC["caption"])
    if number != TABLE_SPEC["expect_number"]:
        raise ScrapeError(f"expected Table {TABLE_SPEC['expect_number']} but the file calls it Table {number}. "
                          f"Check the table is the right one, then update expect_number here and the "
                          f"table references in metric.yml.")
    for i, table in enumerate(pieces):
        header_rows, _ = split_header(grid_rows(table))
        parts = column_headings(header_rows)
        width = max(parts) + 1
        got = {c: [x.lower() for x in p] for c, p in parts.items()}
        if width != EXPECTED_WIDTH or got != EXPECTED_HEADINGS:
            shown = {c: " | ".join(p) for c, p in sorted(parts.items())}
            raise ScrapeError(f"Table {number}, piece {i + 1}: the header layout is not the one this scraper reads "
                              f"(expected {EXPECTED_WIDTH} columns with the headings in EXPECTED_HEADINGS; found "
                              f"{width} columns: {shown}). Nothing was read.")
    return number, len(pieces)


def parse_table_b1(source, budget_year, log=print):
    """Parses Table B.1 from Appendix B (a path or bytes). Returns (info, {start_year: record}).

    Each record has 'period', 'ucb' and 'ucb_pct_gdp' (Decimals, sign as published).
    Raises ScrapeError on a changed header, a missing or duplicate year, or an unreadable value.
    """
    document = open_docx(source)
    check_layout(document)
    start_year = int(budget_year[:4])
    info, rows = parse_debt_table(document, TABLE_SPEC, start_year, log)
    check_sequence(rows, info["table"], start_year)
    return info, rows


def parse_part1_ucb(source, budget_year):
    """The underlying cash balance row of the Part 1 overview table, outcome year, in $ billion
    and per cent of GDP, as Part 1 prints them."""
    document = open_docx(source)
    number, tables = find_tables(document, r"^Overview of key Australian Government general government sector budget aggregates$")
    if len(tables) != 1:
        raise ScrapeError(f"Part 1 overview table: expected one piece, found {len(tables)}")
    header_rows, data_rows = split_header(grid_rows(tables[0]))
    parts = column_headings(header_rows)
    col = pick_column(parts, lambda j, p: budget_year in j and "outcome" in j and "$b" in p, f"{budget_year} outcome, $b")
    labels = [FOOTNOTE.sub("", r[0][2]).strip() for r in data_rows]
    idx = [i for i, label in enumerate(labels) if label == "Underlying cash balance"]
    if len(idx) != 1:
        raise ScrapeError(f"Part 1 Table {number}: expected one row labelled 'Underlying cash balance', found {len(idx)}")
    i = idx[0]
    if i + 1 >= len(data_rows) or labels[i + 1] != "Per cent of GDP":
        raise ScrapeError(f"Part 1 Table {number}: the row after 'Underlying cash balance' is not 'Per cent of GDP'")
    return {"table": number, "column": " | ".join(parts[col]),
            "ucb_b": parse_number(cell_at(data_rows[i], col)),
            "ucb_pct": parse_number(cell_at(data_rows[i + 1], col))}


def crosscheck(latest, p1):
    """Latest-year Appendix B figures against Part 1, rounded the way Part 1 prints them.
    Returns a list of (name, appendix_value, part1_value, matches)."""
    rows = [
        ("underlying cash balance, $b", one_decimal(latest["ucb"] / 1000), p1["ucb_b"]),
        ("underlying cash balance, % of GDP", one_decimal(latest["ucb_pct_gdp"]), p1["ucb_pct"]),
    ]
    return [(n, a, b, a == b) for n, a, b in rows]


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


def run(budget_year, root=ROOT, fetcher=fetch, log=print):
    if not re.fullmatch(r"\d{4}-\d{2}", budget_year):
        raise ScrapeError(f"budget year folder must look like 2025-26, got {budget_year!r}")
    start = int(budget_year[:4])
    if int(budget_year[5:]) != (start + 1) % 100:
        raise ScrapeError(f"{budget_year} is not a financial year")
    metric_dir = Path(root) / "metrics" / "budget-balance"
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

    info, parsed = parse_table_b1(appendix_bytes, budget_year, log)
    log(f"Found Table {info['table']} in {info['pieces']} piece(s) (the first plus any '(continued)'); header layout as expected.")
    for key, heading in info["columns"].items():
        log(f"  {key}: column headings '{heading}'")
    years = sorted(parsed)
    log(f"Years: {parsed[years[0]]['period']} to {parsed[years[-1]]['period']} ({len(years)} years, no gaps, no duplicates)")
    log(f"Estimate or projection rows skipped: {len(skipped)}" + ("" if skipped else " (none found)"))

    rows = build_rows(parsed)

    p1 = parse_part1_ucb(part1_bytes, budget_year)
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
    log(f"Wrote {len(rows)} rows to metrics/budget-balance/data.csv, saved {len(files)} source files and the manifest.")
    return {"info": info, "parsed": parsed, "part1": p1, "crosscheck": results, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download and parse the underlying cash balance from the Final Budget Outcome.")
    ap.add_argument("year", nargs="?", default=DEFAULT_YEAR, help="budget year folder, e.g. 2025-26 (default: the debt scraper's)")
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
