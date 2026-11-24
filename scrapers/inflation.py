#!/usr/bin/env python3
"""Inflation scraper: three series, one metric folder (metrics/inflation/).

1. headline_quarterly: year-ended headline CPI inflation, quarterly, from the Reserve Bank's table
   G1 (series GCPIAGYP), from 1950-Q1. Stored as published. Every quarter is checked against the
   year-ended change worked out in code from the ABS quarterly CPI index (Data API CPI
   1.10001.10.50.Q); all must agree, and the latest quarter must be the same in both.
2. trimmed_mean_quarterly: year-ended trimmed mean, quarterly, seasonally adjusted, from the ABS
   Data API (CPI_Q 3.999902.20.50.Q). Checked against G1 (series GCPIOCPMTMYP): from 2002-Q1 every
   quarter must agree, and the latest quarter must match. Before 2002 the two differ in some
   quarters; each difference is printed and counted but does not stop the scraper.
3. headline_monthly: year-ended headline inflation from the complete monthly CPI, from the ABS Data
   API (CPI 3.10001.10.50.M), checked month by month against the ABS spreadsheet Table 1 (640101.xlsx).

Run from anywhere:  python3 scrapers/inflation.py

If any check fails (a non-200 answer, an unexpected code, a repeated or missing period, an unreadable
value, a cross-check disagreeing, fewer rows than before) nothing is written and the exit code is 1.

The ABS leaves the DECIMALS cell empty for these CPI series. The percentage figures are accepted only
if the API's own text already has at most one decimal place (and are written with exactly one); a
figure with more places is refused, never rounded. See abs_series.parse_sdmx_series.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import abs_series as abs_
from abs_series import ScrapeError
from cpi_june import write_atomic

ROOT = Path(__file__).resolve().parents[1]
SLUG = "inflation"

G1_URL = "https://www.rba.gov.au/statistics/tables/csv/g1-data.csv"
INDEX_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI/1.10001.10.50.Q"
TRIMMED_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI_Q/3.999902.20.50.Q"
MONTHLY_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI/3.10001.10.50.M"
LATEST_URL = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release"
SHEET_ENDING = "/640101.xlsx"

G1_NAME = "rba-g1-data.csv"
INDEX_NAME = "abs-cpi-1.10001.10.50.Q.csv"
TRIMMED_NAME = "abs-cpi_q-3.999902.20.50.Q.csv"
MONTHLY_NAME = "abs-cpi-3.10001.10.50.M.csv"
SHEET_NAME = "abs-cpi-640101.xlsx"

G1_HEADLINE_ID = "GCPIAGYP"
G1_TRIMMED_ID = "GCPIOCPMTMYP"
FIRST_QUARTER = "1950-Q1"       # the owner's decision: no chart starts before 1950
TRIMMED_AGREE_FROM = "2002-Q1"  # from here the ABS trimmed mean and G1 must agree exactly

# Dimension codes that must be constant in each API response. Quarterly CPI index: measure 1 (index
# numbers), index 10001 (all groups), TSEST 10 (original), region 50 (weighted average of eight
# capitals), frequency Q. Trimmed mean: measure 3 (percentage change from the corresponding quarter
# of the previous year), index 999902 (trimmed mean), TSEST 20 (seasonally adjusted). Monthly:
# measure 3, index 10001, TSEST 10, region 50, frequency M.
EXPECTED_INDEX = {
    "DATAFLOW": lambda v: v.startswith("ABS:CPI("),
    "MEASURE": "1", "INDEX": "10001", "TSEST": "10", "REGION": "50", "FREQ": "Q", "UNIT_MEASURE": "IN",
}
EXPECTED_TRIMMED = {
    "DATAFLOW": lambda v: v.startswith("ABS:CPI_Q("),
    "MEASURE": "3", "INDEX": "999902", "TSEST": "20", "REGION": "50", "FREQ": "Q", "UNIT_MEASURE": "PCT",
}
EXPECTED_MONTHLY = {
    "DATAFLOW": lambda v: v.startswith("ABS:CPI("),
    "MEASURE": "3", "INDEX": "10001", "TSEST": "10", "REGION": "50", "FREQ": "M", "UNIT_MEASURE": "PCT",
}
# What to find in Table 1's row 1 headers, and what the column must say about itself.
SHEET_HEADER_TEXT = ["Percentage Change from Corresponding Month of Previous Year", "All groups CPI ;  Australia"]
SHEET_META = {"Series Type": "Original", "Unit": "Percent"}

JURISDICTION = "Australia"
UNIT = "pct"
STATUS = "actual"
HEADER = "date,period,series,jurisdiction,value,unit,status"
# series id -> the label used in messages. Rows in data.csv are sorted by series id, then date.
SERIES = {
    "headline_quarterly": "headline quarterly CPI",
    "headline_monthly": "headline monthly CPI",
    "trimmed_mean_quarterly": "trimmed mean (quarterly)",
}


# ---------------------------------------------------------------- the Reserve Bank's table G1

G1_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
QUARTER_END_MONTH_DAY = {(3, 31): 1, (6, 30): 2, (9, 30): 3, (12, 31): 4}


def parse_g1(raw, series_ids, label="Reserve Bank table G1"):
    """Reads columns of the Reserve Bank's G1 CSV by their Series ID.

    The 'Series ID' row is found by its first cell (it is row 11 today). Dates are dd/mm/yyyy at the
    end of a quarter. Rows with no date, and quarters with an empty cell (the empty future-dated
    rows), are skipped. Returns {series id: {period like 1950-Q1: value text}}.

    Refuses on: text that cannot be read; no or several 'Series ID' rows; a series ID that is missing
    or appears twice; a date that is not dd/mm/yyyy or not a quarter end; a quarter that appears
    twice; a value that is not a number; a quarter missing inside a series.
    """
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    rows = list(csv.reader(io.StringIO(text)))
    id_rows = [i for i, r in enumerate(rows[:40]) if r and r[0].strip() == "Series ID"]
    if len(id_rows) != 1:
        raise ScrapeError(f"{label}: expected one 'Series ID' row in the first 40 rows, found {len(id_rows)}")
    id_row = id_rows[0]
    cols = {}
    for sid in series_ids:
        found = [j for j, v in enumerate(rows[id_row]) if v.strip() == sid]
        if len(found) != 1:
            raise ScrapeError(f"{label}: series ID {sid} appears {len(found)} times in the Series ID row; expected once")
        cols[sid] = found[0]
    out = {sid: {} for sid in series_ids}
    seen = set()
    for k, r in enumerate(rows[id_row + 1:], start=id_row + 2):
        if not r or not r[0].strip():
            continue  # a row with no date (G1 ends with empty rows)
        m = G1_DATE_RE.fullmatch(r[0].strip())
        if not m:
            raise ScrapeError(f"{label}: row {k} has {r[0]!r} where a date like 31/03/1950 was expected")
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if (mo, d) not in QUARTER_END_MONTH_DAY:
            raise ScrapeError(f"{label}: row {k} has the date {r[0]!r}, which is not the last day of a quarter")
        period = f"{y:04d}-Q{QUARTER_END_MONTH_DAY[(mo, d)]}"
        if period in seen:
            raise ScrapeError(f"{label}: quarter {period} appears twice (row {k})")
        seen.add(period)
        for sid, j in cols.items():
            v = r[j].strip() if len(r) > j else ""
            if v == "":
                continue  # not yet published, or before the series starts
            if not abs_.VALUE_RE.fullmatch(v):
                raise ScrapeError(f"{label}: row {k} ({period}) column {sid} has an unreadable value {v!r}")
            out[sid][period] = v
    for sid, vals in out.items():
        if not vals:
            raise ScrapeError(f"{label}: column {sid} holds no values")
        abs_.require_no_missing_quarters(vals.keys(), f"{label} column {sid}")
    return out


def one_decimal(text, where):
    """Checks that a published figure already has at most one decimal place and writes it with
    exactly one ("3" becomes "3.0"). Never rounds."""
    places = len(text.split(".")[1]) if "." in text else 0
    if places > 1:
        raise ScrapeError(f"{where} is {text!r}, with more than one decimal place; it is stored as published and is not rounded")
    return abs_.round_half_up(text, 1)


# ---------------------------------------------------------------- the cross-checks

def check_headline_against_index(g1_values, index_series, log=print):
    """Series 1. For every quarter from FIRST_QUARTER to the latest in G1, works out
    (index_t / index_{t-4} - 1) * 100 from the ABS index with Decimal, rounds it half up to one
    decimal, and requires it to equal G1's figure exactly. The latest quarter must be the same in
    both. Returns (quarters compared, first, last)."""
    index = {p: Decimal(v) for p, v in index_series.pairs}
    g1_latest, index_latest = max(g1_values), max(index)
    if g1_latest != index_latest:
        raise ScrapeError(f"the latest quarter differs: G1 ends at {g1_latest}, the ABS index at {index_latest}")
    kept = sorted(p for p in g1_values if p >= FIRST_QUARTER)
    if not kept or kept[0] != FIRST_QUARTER:
        raise ScrapeError(f"G1 has no figure for {FIRST_QUARTER}, where the series must start")
    bad = []
    for p in kept:
        prev = abs_.previous_quarter(p, 4)
        if p not in index or prev not in index:
            raise ScrapeError(f"the ABS index has no figure for {p if p not in index else prev}, needed to check {p}")
        if index[prev] == 0:
            raise ScrapeError(f"the ABS index for {prev} is zero")
        computed = ((index[p] / index[prev] - 1) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if computed != Decimal(g1_values[p]):
            bad.append(f"{p}: G1 {g1_values[p]}, ABS index gives {computed}")
    if bad:
        shown = "; ".join(bad[:10]) + (f"; and {len(bad) - 10} more" if len(bad) > 10 else "")
        raise ScrapeError(f"G1 and the ABS quarterly index disagree in {len(bad)} quarter(s): {shown}")
    log(f"Cross-check (headline quarterly): {len(kept)} quarters agree with the year-ended change worked out from the ABS index "
        f"({kept[0]} to {kept[-1]}); the latest quarter is {g1_latest} in both.")
    return len(kept), kept[0], kept[-1]


def check_trimmed_against_g1(trimmed_pairs, g1_values, log=print):
    """Series 2. Compares the ABS trimmed mean with G1's GCPIOCPMTMYP.

    From TRIMMED_AGREE_FROM every quarter must be in G1 and agree exactly. Earlier quarters that
    differ are printed and counted, not refused. The latest quarter must be the same in both.
    Returns a dict: compared, agree, agree_from_2002, differences (list of (period, abs, g1, diff)),
    largest (Decimal), first, last."""
    abs_values = dict(trimmed_pairs)
    abs_latest, g1_latest = max(abs_values), max(g1_values)
    if abs_latest != g1_latest:
        raise ScrapeError(f"the latest trimmed mean quarter differs: the ABS ends at {abs_latest}, G1 at {g1_latest}")
    common = sorted(set(abs_values) & set(g1_values))
    if not common:
        raise ScrapeError("the ABS trimmed mean and G1 have no quarter in common")
    missing = sorted(p for p in abs_values if p >= TRIMMED_AGREE_FROM and p not in g1_values)
    if missing:
        raise ScrapeError(f"G1 has no trimmed mean figure for {', '.join(missing[:10])}, from {TRIMMED_AGREE_FROM} on where it must agree")
    differences, late = [], []
    for p in common:
        a, g = Decimal(abs_values[p]), Decimal(one_decimal(g1_values[p], f"G1 trimmed mean for {p}"))
        if a != g:
            (late if p >= TRIMMED_AGREE_FROM else differences).append((p, abs_values[p], g1_values[p], abs(a - g)))
    if late:
        shown = "; ".join(f"{p}: ABS {a}, G1 {g}" for p, a, g, _ in late[:10]) + (f"; and {len(late) - 10} more" if len(late) > 10 else "")
        raise ScrapeError(f"the ABS trimmed mean and G1 disagree in {len(late)} quarter(s) from {TRIMMED_AGREE_FROM}, where they must agree: {shown}")
    largest = max((d[3] for d in differences), default=Decimal(0))
    n_late = sum(1 for p in common if p >= TRIMMED_AGREE_FROM)
    log(f"Cross-check (trimmed mean): {len(common)} quarters compared ({common[0]} to {common[-1]}); {len(common) - len(differences)} agree; "
        f"all {n_late} quarters from {TRIMMED_AGREE_FROM} agree; the latest quarter is {abs_latest} in both.")
    log(f"Trimmed mean, quarters before {TRIMMED_AGREE_FROM} where the ABS and G1 differ: {len(differences)}"
        + (f", largest difference {largest} points." if differences else "."))
    for p, a, g, d in differences:
        log(f"  {p}: ABS {a}, G1 {g}, difference {d}")
    return {"compared": len(common), "agree": len(common) - len(differences), "agree_from_2002": n_late,
            "differences": differences, "largest": largest, "first": common[0], "last": common[-1]}


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


def date_of(series, period):
    return abs_.month_end(period) if series == "headline_monthly" else abs_.quarter_end(period)


def build_csv(series_pairs):
    """series_pairs: {series id: [(period, value text)]}. Sorted by series id then period, so the
    same figures always give the same bytes."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER.split(","))
    for series in sorted(series_pairs):
        for period, value in sorted(series_pairs[series]):
            w.writerow([date_of(series, period), period, series, JURISDICTION, value, UNIT, STATUS])
    return buf.getvalue().encode("utf-8")


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # Series 1 and its check
    log(f"Downloading {G1_URL}")
    raw_g1 = fetcher(G1_URL, "text/csv")
    g1 = parse_g1(raw_g1, [G1_HEADLINE_ID, G1_TRIMMED_ID])
    log(f"Downloading {INDEX_URL}")
    raw_index = fetcher(INDEX_URL, abs_.ACCEPT_SDMX)
    index = abs_.parse_sdmx_series(raw_index, EXPECTED_INDEX, label="the ABS quarterly CPI index", freq="Q", blank_decimals="raw")
    g1_headline = g1[G1_HEADLINE_ID]
    headline = [(p, one_decimal(g1_headline[p], f"G1 {G1_HEADLINE_ID} for {p}")) for p in sorted(g1_headline) if p >= FIRST_QUARTER]
    log(f"G1 {G1_HEADLINE_ID}: {len(headline)} quarters kept, {headline[0][0]} to {headline[-1][0]}, none missing. Latest value {headline[-1][1]}.")
    n_checked, first_checked, last_checked = check_headline_against_index(g1_headline, index, log)

    # Series 2 and its check
    log(f"Downloading {TRIMMED_URL}")
    raw_trimmed = fetcher(TRIMMED_URL, abs_.ACCEPT_SDMX)
    trimmed = abs_.parse_sdmx_series(raw_trimmed, EXPECTED_TRIMMED, label="the ABS trimmed mean response", freq="Q", blank_decimals=1)
    log(f"Trimmed mean: {len(trimmed.pairs)} quarters, {trimmed.pairs[0][0]} to {trimmed.pairs[-1][0]}, none missing. Latest value {trimmed.pairs[-1][1]}.")
    trimmed_check = check_trimmed_against_g1(trimmed.pairs, g1[G1_TRIMMED_ID], log)

    # Series 3 and its check
    log(f"Downloading {MONTHLY_URL}")
    raw_monthly = fetcher(MONTHLY_URL, abs_.ACCEPT_SDMX)
    monthly = abs_.parse_sdmx_series(raw_monthly, EXPECTED_MONTHLY, label="the ABS monthly CPI response", freq="M", blank_decimals=1)
    log(f"Monthly CPI: {len(monthly.pairs)} months, {monthly.pairs[0][0]} to {monthly.pairs[-1][0]}, none missing. Latest value {monthly.pairs[-1][1]}.")
    log(f"Looking for the current Table 1 link on {LATEST_URL}")
    page = fetcher(LATEST_URL, "text/html")
    sheet_url = abs_.find_link(page, LATEST_URL, SHEET_ENDING)
    log(f"Downloading {sheet_url}")
    raw_sheet = fetcher(sheet_url, "*/*")
    sheet_id = abs_.find_series_id_by_header(raw_sheet, SHEET_HEADER_TEXT)
    sheet_values = abs_.parse_spreadsheet_series(raw_sheet, sheet_id, expected_meta=SHEET_META)
    log(f"Spreadsheet column {sheet_id}: {len(sheet_values)} months, {min(sheet_values)} to {max(sheet_values)}.")
    monthly_check = abs_.cross_check(monthly, sheet_values, log)

    series_pairs = {"headline_quarterly": headline, "trimmed_mean_quarterly": trimmed.pairs, "headline_monthly": monthly.pairs}

    # Rows never fall
    data_path = root / "metrics" / SLUG / "data.csv"
    old = existing_counts(data_path)
    for series, pairs in series_pairs.items():
        if series in old:
            old_count, old_first = old[series]
            if len(pairs) < old_count:
                raise ScrapeError(f"{SERIES[series]} now has {len(pairs)} rows, fewer than the {old_count} already in data.csv. Rows must never fall.")
            if pairs[0][0] > old_first:
                raise ScrapeError(f"{SERIES[series]} now starts at {pairs[0][0]}, later than the {old_first} already in data.csv.")
    for series in old:
        if series not in series_pairs:
            raise ScrapeError(f"data.csv has the series {series}, which this run did not produce.")

    # Nothing has failed: write everything.
    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name, url, raw in ((G1_NAME, G1_URL, raw_g1), (INDEX_NAME, INDEX_URL, raw_index), (TRIMMED_NAME, TRIMMED_URL, raw_trimmed),
                           (MONTHLY_NAME, MONTHLY_URL, raw_monthly), (SHEET_NAME, sheet_url, raw_sheet)):
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(series_pairs))
    total = sum(len(p) for p in series_pairs.values())
    log(f"Wrote metrics/{SLUG}/data.csv ({total} rows), saved all five raw downloads and the manifest.")
    return {"series": series_pairs, "headline_check": (n_checked, first_checked, last_checked),
            "trimmed_check": trimmed_check, "monthly_check": monthly_check, "sheet_id": sheet_id, "sheet_url": sheet_url}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download Australian inflation figures and write their data file.")
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
