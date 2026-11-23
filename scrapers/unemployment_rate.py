#!/usr/bin/env python3
"""Unemployment rate scraper.

Downloads the monthly unemployment rate (persons, all ages 15+, seasonally adjusted, Australia)
from the ABS Data API, checks it month by month against the ABS Labour Force spreadsheet
(Table 1, series A84423050A), saves both raw downloads unchanged, and writes
metrics/unemployment-rate/data.csv.

Run from anywhere:  python3 scrapers/unemployment_rate.py

If any check fails (a wrong series code, a missing or repeated month, an unreadable value, the two
sources disagreeing about any month or about the latest month, fewer rows than before) nothing is
written and the exit code is 1.

The spreadsheet's address contains the release month (.../oct-2026/62020001.xlsx), so the current
address is read from the Labour Force "latest release" page each time.
"""
import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import abs_series as abs_
from abs_series import ScrapeError
from cpi_june import write_atomic

ROOT = Path(__file__).resolve().parents[1]
SLUG = "unemployment-rate"

API_URL = "https://data.api.abs.gov.au/rest/data/ABS,LF/M13.3.1599.20.AUS.M"
LATEST_URL = "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/latest-release"
SHEET_ENDING = "/62020001.xlsx"
SHEET_ID = "A84423050A"
API_NAME = "abs-lf-M13.3.1599.20.AUS.M.csv"
SHEET_NAME = "abs-lf-62020001.xlsx"

# The ABS key M13.3.1599.20.AUS.M means: measure M13 (unemployment rate), sex 3 (persons), age 1599
# (all ages 15 and over), TSEST 20 (seasonally adjusted), region AUS (Australia), frequency M
# (monthly). These columns must be constant. UNIT_MEASURE must be PCT, and the dataflow must be the
# labour force one (the version number may change).
EXPECTED = {
    "DATAFLOW": lambda v: v.startswith("ABS:LF("),
    "MEASURE": "M13", "SEX": "3", "AGE": "1599", "TSEST": "20", "REGION": "AUS", "FREQ": "M",
    "UNIT_MEASURE": "PCT",
}
# What the spreadsheet column must say about itself (whitespace is ignored).
SHEET_META = {"description": "Unemployment rate ; Persons ;", "Series Type": "Seasonally Adjusted", "Unit": "Percent"}

SERIES = "unemployment_rate"
JURISDICTION = "Australia"
UNIT = "pct"
STATUS = "actual"
HEADER = "date,period,series,jurisdiction,value,unit,status"


def existing_rows(path: Path):
    """Returns (row count, first period) of an existing data.csv, or (0, None)."""
    if not path.exists():
        return 0, None
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    if not rows:
        return 0, None
    return len(rows), min(r["period"] for r in rows)


def build_csv(pairs):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER.split(","))
    for period, value in sorted(pairs):  # sorted, so the same figures always give the same bytes
        w.writerow([abs_.month_end(period), period, SERIES, JURISDICTION, value, UNIT, STATUS])
    return buf.getvalue().encode("utf-8")


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)
    log(f"Downloading {API_URL}")
    raw_api = fetcher(API_URL, abs_.ACCEPT_SDMX)
    series = abs_.parse_sdmx_series(raw_api, EXPECTED)
    pairs = series.pairs
    log(f"API: {len(pairs)} months, {pairs[0][0]} to {pairs[-1][0]}, none missing. Latest value {pairs[-1][1]}.")

    log(f"Looking for the current spreadsheet link on {LATEST_URL}")
    page = fetcher(LATEST_URL, "text/html")
    sheet_url = abs_.find_link(page, LATEST_URL, SHEET_ENDING)
    log(f"Downloading {sheet_url}")
    raw_sheet = fetcher(sheet_url, "*/*")
    sheet_values = abs_.parse_spreadsheet_series(raw_sheet, SHEET_ID, expected_meta=SHEET_META)
    log(f"Spreadsheet column {SHEET_ID}: {len(sheet_values)} months, {min(sheet_values)} to {max(sheet_values)}.")
    abs_.cross_check(series, sheet_values, log)

    data_path = root / "metrics" / SLUG / "data.csv"
    old_count, old_first = existing_rows(data_path)
    if len(pairs) < old_count:
        raise ScrapeError(f"the new data has {len(pairs)} rows, fewer than the {old_count} already in data.csv. Rows must never fall.")
    if old_first is not None and pairs[0][0] > old_first:
        raise ScrapeError(f"the series now starts at {pairs[0][0]}, later than the {old_first} already in data.csv.")

    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name, url, raw in ((API_NAME, API_URL, raw_api), (SHEET_NAME, sheet_url, raw_sheet)):
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(pairs))
    log(f"Wrote metrics/{SLUG}/data.csv ({len(pairs)} rows), saved both raw downloads and the manifest.")
    return pairs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download the ABS unemployment rate and write its data file.")
    ap.add_argument("--root", default=str(ROOT), help="project folder to write into (default: this project)")
    args = ap.parse_args(argv)
    try:
        run(root=args.root)
    except ScrapeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
