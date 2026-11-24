#!/usr/bin/env python3
"""Wages and prices scraper: two series, one metric folder (metrics/wages-and-prices/).

1. wage_growth: year-ended change in the ABS Wage Price Index, total hourly rates of pay excluding
   bonuses, private and public sectors, all industries, seasonally adjusted, Australia, quarterly,
   from the ABS Data API (WPI 3.THRPEB.7.TOT.20.AUS.Q). The response starts with blank values
   (OBS_STATUS u) for 1997-Q3 to 1998-Q2: leading blanks, and only leading blanks, are skipped. The
   response has no DECIMALS column, so a figure is accepted only if it already has at most one
   decimal place (and is written with exactly one); a figure with more is refused, never rounded.
   Every quarter is checked against the ABS spreadsheet Table 1 (634501.xlsx, found on the Wage
   Price Index "latest release" page), column series ID A83895396W. All quarters must agree and the
   latest quarter must be the same in both.
2. price_growth: the same figures as the inflation page's headline_quarterly series, copied from
   metrics/inflation/data.csv for the quarters from the first wage quarter on. Nothing is downloaded
   for it. The path and checksum of the inflation file at the time of copying go in
   sources/manifest.json (the file itself is not copied there). The inflation scraper must have run
   first (run_all.py runs it earlier and skips this scraper if it failed). The validator checks that
   every price_growth row equals the inflation row for the same date (copy_of in metric.yml).

Run from anywhere:  python3 scrapers/wages_and_prices.py

If any check fails (a non-200 answer, an unexpected code, a repeated or missing quarter, a blank
after the first figure, an unreadable value, a figure with more than one decimal place, the
spreadsheet disagreeing, the inflation file missing or with a gap, fewer rows than before) nothing is
written and the exit code is 1.
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
SLUG = "wages-and-prices"

API_URL = "https://data.api.abs.gov.au/rest/data/ABS,WPI/3.THRPEB.7.TOT.20.AUS.Q"
LATEST_URL = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia/latest-release"
SHEET_ENDING = "/634501.xlsx"
SHEET_ID = "A83895396W"
API_NAME = "abs-wpi-3.THRPEB.7.TOT.20.AUS.Q.csv"
SHEET_NAME = "abs-wpi-634501.xlsx"

# The ABS key 3.THRPEB.7.TOT.20.AUS.Q means: measure 3 (percentage change from the corresponding
# quarter of the previous year), index THRPEB (total hourly rates of pay excluding bonuses), sector 7
# (private and public), industry TOT (all industries), TSEST 20 (seasonally adjusted), region AUS,
# frequency Q. These columns must be constant. The dataflow version may change.
EXPECTED = {
    "DATAFLOW": lambda v: v.startswith("ABS:WPI("),
    "MEASURE": "3", "INDEX": "THRPEB", "SECTOR": "7", "INDUSTRY": "TOT", "TSEST": "20", "REGION": "AUS", "FREQ": "Q",
    "UNIT_MEASURE": "PCT",
}
# What the spreadsheet column must say about itself (whitespace is ignored).
SHEET_META = {
    "description": "Percentage Change From Corresponding Quarter of Previous Year ; Australia ; "
                   "Total hourly rates of pay excluding bonuses ; Private and Public ; All industries ;",
    "Series Type": "Seasonally Adjusted",
    "Unit": "Percent",
}

# The inflation page's data, copied (not downloaded) for price_growth.
INFLATION_SLUG = "inflation"
INFLATION_SERIES = "headline_quarterly"
INFLATION_MANIFEST_KEY = "copied-from-metrics-inflation-data.csv"
INFLATION_HEADER = "date,period,series,jurisdiction,value,unit,status"

JURISDICTION = "Australia"
UNIT = "pct"
STATUS = "actual"
HEADER = "date,period,series,jurisdiction,value,unit,status"
SERIES = {"wage_growth": "wage growth", "price_growth": "price growth"}


def one_decimal(text, where):
    """Checks that a figure already has at most one decimal place and writes it with exactly one
    ("3" becomes "3.0"). Never rounds."""
    places = len(text.split(".")[1]) if "." in text else 0
    if places > 1:
        raise ScrapeError(f"{where} is {text!r}, with more than one decimal place; it is stored as published and is not rounded")
    return abs_.round_half_up(text, 1)


# ---------------------------------------------------------------- the inflation page's figures

def read_inflation(root, first_quarter, last_quarter, log=print):
    """Reads metrics/inflation/data.csv (series headline_quarterly) and returns
    (rows, sha256 of the file, byte count), where rows is [(period, value text)] for every quarter
    from `first_quarter` to the file's own latest quarter.

    Refuses if the file is missing or unreadable, has no headline_quarterly rows, has no figure for
    `first_quarter` (so the copy could not start where the wages start), ends before `last_quarter`
    (the latest wage quarter, so the price line would stop short of the wage line), has a quarter
    missing inside the range, or has a date that is not the last day of its quarter."""
    path = Path(root) / "metrics" / INFLATION_SLUG / "data.csv"
    if not path.is_file():
        raise ScrapeError(f"{path} is missing. The inflation scraper must run before this one; price growth is copied from it.")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{path} is not text: {e}") from None
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or ",".join(rows[0]) != INFLATION_HEADER:
        raise ScrapeError(f"{path} does not have the header {INFLATION_HEADER}")
    found = {}
    for k, r in enumerate(rows[1:], start=2):
        if len(r) != 7:
            raise ScrapeError(f"{path}: line {k} has {len(r)} fields; expected 7")
        date, period, series, _jur, value, unit, _status = r
        if series != INFLATION_SERIES:
            continue
        if not abs_.QUARTER_RE.fullmatch(period) or abs_.quarter_end(period) != date:
            raise ScrapeError(f"{path}: line {k} has the period {period!r} on {date}; a quarter label and its last day were expected")
        if unit != UNIT:
            raise ScrapeError(f"{path}: line {k} ({period}) has the unit {unit!r}, expected {UNIT}")
        if period in found:
            raise ScrapeError(f"{path}: {INFLATION_SERIES} has {period} twice")
        if not abs_.VALUE_RE.fullmatch(value):
            raise ScrapeError(f"{path}: line {k} ({period}) has an unreadable value {value!r}")
        found[period] = one_decimal(value, f"{path}: line {k} ({period})")
    if not found:
        raise ScrapeError(f"{path} has no {INFLATION_SERIES} rows")
    if first_quarter not in found:
        raise ScrapeError(f"{path} has no {INFLATION_SERIES} figure for {first_quarter}, where price growth must start (the first wage quarter)")
    kept = sorted(p for p in found if p >= first_quarter)
    abs_.require_no_missing_quarters(kept, f"{path} {INFLATION_SERIES} from {first_quarter}")
    if kept[-1] < last_quarter:
        raise ScrapeError(f"{path} {INFLATION_SERIES} ends at {kept[-1]}, before the latest wage quarter {last_quarter}")
    pairs = [(p, found[p]) for p in kept]
    sha = hashlib.sha256(raw).hexdigest()
    log(f"Inflation page data ({INFLATION_SERIES}): {len(pairs)} quarters copied, {pairs[0][0]} to {pairs[-1][0]}, none missing. "
        f"Latest value {pairs[-1][1]}. metrics/inflation/data.csv sha256 {sha}.")
    return pairs, sha, len(raw)


# ---------------------------------------------------------------- the data file

def existing_counts(path: Path):
    """{series: (row count, first period)} of an existing data.csv (empty if there is none)."""
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        n, first = out.get(r["series"], (0, None))
        out[r["series"]] = (n + 1, r["period"] if first is None else min(first, r["period"]))
    return out


def build_csv(series_pairs):
    """series_pairs: {series id: [(period, value text)]}. Sorted by series id then period, so the
    same figures always give the same bytes."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER.split(","))
    for series in sorted(series_pairs):
        for period, value in sorted(series_pairs[series]):
            w.writerow([abs_.quarter_end(period), period, series, JURISDICTION, value, UNIT, STATUS])
    return buf.getvalue().encode("utf-8")


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # Series 1 and its check
    log(f"Downloading {API_URL}")
    raw_api = fetcher(API_URL, abs_.ACCEPT_SDMX)
    series = abs_.parse_sdmx_series(raw_api, EXPECTED, label="the ABS Wage Price Index response", freq="Q",
                                    blank_decimals=1, skip_leading_blank=True)
    wages = series.pairs
    log(f"API: {len(wages)} quarters, {wages[0][0]} to {wages[-1][0]}, none missing; {len(series.skipped)} leading blank quarter(s) skipped"
        f"{' (' + series.skipped[0] + ' to ' + series.skipped[-1] + ')' if series.skipped else ''}. Latest value {wages[-1][1]}.")

    log(f"Looking for the current Table 1 link on {LATEST_URL}")
    page = fetcher(LATEST_URL, "text/html")
    sheet_url = abs_.find_link(page, LATEST_URL, SHEET_ENDING)
    log(f"Downloading {sheet_url}")
    raw_sheet = fetcher(sheet_url, "*/*")
    sheet_values = abs_.parse_spreadsheet_series(raw_sheet, SHEET_ID, expected_meta=SHEET_META, freq="Q")
    log(f"Spreadsheet column {SHEET_ID}: {len(sheet_values)} quarters, {min(sheet_values)} to {max(sheet_values)}.")
    if set(sheet_values) != set(series.raw_values):
        only_api = sorted(set(series.raw_values) - set(sheet_values))
        only_sheet = sorted(set(sheet_values) - set(series.raw_values))
        raise ScrapeError(f"the API and the spreadsheet cover different quarters: only in the API {only_api[:10]}, only in the spreadsheet {only_sheet[:10]}")
    check = abs_.cross_check(series, sheet_values, log, noun="quarter")

    # Series 2: copied from the inflation page's data
    prices, inflation_sha, inflation_bytes = read_inflation(root, wages[0][0], wages[-1][0], log)

    series_pairs = {"wage_growth": wages, "price_growth": prices}

    # Rows never fall
    data_path = root / "metrics" / SLUG / "data.csv"
    old = existing_counts(data_path)
    for name, pairs in series_pairs.items():
        if name in old:
            old_count, old_first = old[name]
            if len(pairs) < old_count:
                raise ScrapeError(f"{SERIES[name]} now has {len(pairs)} rows, fewer than the {old_count} already in data.csv. Rows must never fall.")
            if pairs[0][0] > old_first:
                raise ScrapeError(f"{SERIES[name]} now starts at {pairs[0][0]}, later than the {old_first} already in data.csv.")
    for name in old:
        if name not in series_pairs:
            raise ScrapeError(f"data.csv has the series {name}, which this run did not produce.")

    # Nothing has failed: write everything.
    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name, url, raw in ((API_NAME, API_URL, raw_api), (SHEET_NAME, sheet_url, raw_sheet)):
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    # A reference, not a file in this folder: the validator does not look for it here.
    manifest[INFLATION_MANIFEST_KEY] = {
        "path": f"metrics/{INFLATION_SLUG}/data.csv", "series": INFLATION_SERIES, "retrieved": retrieved,
        "sha256": inflation_sha, "bytes": inflation_bytes,
    }
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(series_pairs))
    total = sum(len(p) for p in series_pairs.values())
    log(f"Wrote metrics/{SLUG}/data.csv ({total} rows), saved both raw downloads and the manifest.")
    return {"series": series_pairs, "check": check, "sheet_id": SHEET_ID, "sheet_url": sheet_url, "inflation_sha256": inflation_sha}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download Australian wage growth, copy price growth from the inflation page, and write the data file.")
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
