#!/usr/bin/env python3
"""New homes scraper: two stored series, one metric folder (metrics/new-homes/).

1. completions: dwelling units completed each quarter, all buildings, total work, total sectors,
   seasonally adjusted, Australia and each state and territory, from the ABS Data API
   (BUILDING_ACTIVITY M7.<region>.CUR.TOT.9.TOT.20.Q). Every code is confirmed from the same request made
   with labels: M7 Dwelling units completed, CUR Current Price, TOT Total Work, 9 Total Sectors, TOT All
   Buildings, 20 Seasonally Adjusted, Q Quarterly, and REGION 1 New South Wales, 2 Victoria, 3 Queensland,
   4 South Australia, 5 Western Australia, 6 Tasmania, 7 Northern Territory, 8 Australian Capital Territory,
   AUS Australia. A different name stops the run. The response has no DECIMALS column and the figures are
   counts: a figure is accepted only if it is a whole number (nothing is rounded).
   Every quarter of every jurisdiction is checked against the ABS Building Activity time series workbooks.
   The "latest release" page lists them with their table titles; the workbooks whose title says "Dwelling
   Unit Completions" are downloaded, and the columns are found by their header text and series type
   (Seasonally Adjusted, unit Number): "Dwelling units completed ; Total Sectors ; Total (Type of Building) ;
   Total (Type of Work) ;" for Australia (Table 37) and "Dwelling units completed ; <state> ; Total (Type of
   Building) ; Total (Type of Work) ; Total Sectors ;" for each state and territory (Table 38). Each header
   must match exactly one column in exactly one workbook. The API and the workbook must cover the same
   quarters, agree in every quarter and end on the same one. The series IDs found are printed.
2. population_june_2024: the estimated resident population at 30 June 2024, Australia and each state and
   territory, copied (not downloaded) from metrics/social-housing/data.csv (series population, date
   2024-06-30). The path and checksum of that file go in sources/manifest.json (as wages-and-prices does for
   the inflation file). It refuses if the social housing file is missing or lacks any of the nine figures.
   The checker (copy_of in metric.yml) enforces that the copy and the original stay equal. The social
   housing scraper must have run first (run_all.py runs it earlier and skips this scraper if it failed).

The cumulative total since July 2024, the rate per 1,000 residents and the straight-line pace are NOT written
here. The site works them out at build time (derive in metric.yml). This scraper only prints them, worked out
separately in Python with exact fractions, for the checking notes.

Run from anywhere:  python3 scrapers/new_homes.py

If any check fails (a non-200 answer, an unexpected code or name, a repeated or missing quarter, a figure
that is not a whole number, a column not found exactly once, the workbooks disagreeing, the population
missing, fewer rows than before) nothing is written and the exit code is 1.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from urllib.parse import urljoin, urlparse

import abs_series as abs_
import social_housing as sh
from abs_series import ScrapeError
from cpi_june import write_atomic

ROOT = Path(__file__).resolve().parents[1]
SLUG = "new-homes"

API_URL = "https://data.api.abs.gov.au/rest/data/ABS,BUILDING_ACTIVITY/M7.AUS+1+2+3+4+5+6+7+8.CUR.TOT.9.TOT.20.Q"
API_LABELS = "application/vnd.sdmx.data+csv;labels=both"
PAGE_URL = "https://www.abs.gov.au/statistics/industry/building-and-construction/building-activity-australia/latest-release"
API_NAME = "abs-building_activity-M7.1-8-AUS.CUR.TOT.9.TOT.20.Q.csv"
LABELS_NAME = "abs-building_activity-M7.1-8-AUS.CUR.TOT.9.TOT.20.Q-with-labels.csv"
TITLE_MUST_CONTAIN = "dwelling unit completions"  # the table title on the ABS page; the header text decides, not the title

# Every dimension of the API key must hold the one expected code (REGION is added for each region).
EXPECTED = {
    "DATAFLOW": lambda v: v.startswith("ABS:BUILDING_ACTIVITY("),
    "MEASURE": "M7", "PRICE_ADJ": "CUR", "BLD_WORK_TYPE": "TOT", "SECTOR_OWN": "9", "TYPE_BLDG": "TOT", "TSEST": "20", "FREQ": "Q",
    "UNIT_MEASURE": "NUM", "UNIT_MULT": "0",
}
# What those codes must be called in the labelled response ('code: name').
LABEL_EXPECT = {
    "MEASURE": "M7: Dwelling units completed", "PRICE_ADJ": "CUR: Current Price", "BLD_WORK_TYPE": "TOT: Total Work",
    "SECTOR_OWN": "9: Total Sectors", "TYPE_BLDG": "TOT: All Buildings", "TSEST": "20: Seasonally Adjusted", "FREQ": "Q: Quarterly",
}
REGIONS = sh.REGIONS  # REGION 1 New South Wales ... 8 Australian Capital Territory, AUS Australia: the same codes as the population
NATIONAL = "Australia"

# What a workbook column must say about itself. Australia's table has no region in the header; the states' table does.
SHEET_HEADERS = {
    NATIONAL: "Dwelling units completed ; Total Sectors ; Total (Type of Building) ; Total (Type of Work) ;",
    **{name: f"Dwelling units completed ; {name} ; Total (Type of Building) ; Total (Type of Work) ; Total Sectors ;" for code, name in REGIONS.items() if code != "AUS"},
}
SHEET_META = {"Series Type": "Seasonally Adjusted", "Unit": "Number"}

# The population copy
POP_SLUG = "social-housing"
POP_SERIES = "population"
POP_DATE = "2024-06-30"
POP_MANIFEST_KEY = "copied-from-metrics-social-housing-data.csv"

# The Accord began on 1 July 2024: the first quarter it counts is 2024-Q3. Used only for the printed check figures.
ACCORD_FIRST_QUARTER = "2024-Q3"
ACCORD_TARGET = 1_200_000
ACCORD_QUARTERS = 20

HEADER = "date,period,series,jurisdiction,value,unit,status"
UNIT = "count"
STATUS = "actual"
OUT_POP = "population_june_2024"
POP_PERIOD = "2024"


# ---------------------------------------------------------------- the workbooks

def candidate_links(html_bytes, page_url):
    """[(table title, full address)] for every workbook on the ABS page whose table title contains
    'Dwelling Unit Completions'. The page lists each time series workbook under an <h4> title. Every address
    must be an https address on www.abs.gov.au. Refuses if there is none."""
    html = html_bytes.decode("utf-8", errors="replace")
    found = []
    for m in re.finditer(r"<h4>(.*?)</h4>(.*?)</li>", html, re.S | re.I):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
        if TITLE_MUST_CONTAIN not in title.lower():
            continue
        for h in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", m.group(2), re.I):
            href = h.group(1).strip().split("#")[0].split("?")[0]
            if not href.lower().endswith(".xlsx"):
                continue
            full = urljoin(page_url, href)
            u = urlparse(full)
            if u.scheme != "https" or u.hostname != "www.abs.gov.au":
                raise ScrapeError(f"the link {full} is not an https address on www.abs.gov.au")
            if (title, full) not in found:
                found.append((title, full))
    if not found:
        raise ScrapeError(f"no workbook whose table title contains 'Dwelling Unit Completions' was found on {page_url}")
    return found


def columns_in(raw):
    """{jurisdiction: [(sheet, series ID)]} for the seasonally adjusted columns of this workbook whose header
    is the one wanted for that jurisdiction. A jurisdiction with no column is absent."""
    out = {}
    for name, header in SHEET_HEADERS.items():
        found = abs_.find_series_ids_by_header(raw, [header], series_type=SHEET_META["Series Type"], label="the ABS Building Activity workbook")
        if found:
            out[name] = found
    return out


def find_columns(candidates, fetcher, log=print):
    """Downloads each candidate workbook and finds, for each of the nine jurisdictions, the one column with the
    wanted header. Refuses unless each jurisdiction has exactly one column in exactly one workbook.
    Returns ({jurisdiction: (url, sheet, series ID)}, {url: raw bytes} of the workbooks used)."""
    hits = {name: [] for name in SHEET_HEADERS}
    raws = {}
    for title, url in candidates:
        raw = fetcher(url, "*/*")
        got = columns_in(raw)
        log(f"  {url.rsplit('/', 1)[-1]} ({title}): " + (f"{len(got)} of {len(SHEET_HEADERS)} jurisdictions have the wanted seasonally adjusted column" if got else "none of the wanted columns"))
        for name, cols in got.items():
            for sheet, sid in cols:
                hits[name].append((url, sheet, sid))
        if got:
            raws[url] = raw
    chosen = {}
    for name, h in hits.items():
        if len(h) != 1:
            raise ScrapeError(f"{name}: {len(h)} workbook columns have the header '{SHEET_HEADERS[name]}' with series type {SHEET_META['Series Type']}; expected exactly one")
        chosen[name] = h[0]
    used = {url for url, _, _ in chosen.values()}
    return chosen, {u: raws[u] for u in raws if u in used}


# ---------------------------------------------------------------- the population copy

def read_population(root, log=print):
    """Reads metrics/social-housing/data.csv and returns ({jurisdiction: value text}, sha256, bytes) for the
    series population on 2024-06-30. Refuses if the file is missing or unreadable, or lacks a figure for any of
    the nine jurisdictions (or has one twice, or one that is not a whole number)."""
    path = Path(root) / "metrics" / POP_SLUG / "data.csv"
    if not path.is_file():
        raise ScrapeError(f"{path} is missing. The social housing scraper must run before this one; the population is copied from it.")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{path} is not text: {e}") from None
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or ",".join(rows[0]) != HEADER:
        raise ScrapeError(f"{path} does not have the header {HEADER}")
    found = {}
    for k, r in enumerate(rows[1:], start=2):
        if len(r) != 7:
            raise ScrapeError(f"{path}: line {k} has {len(r)} fields; expected 7")
        date, _period, series, jur, value, unit, _status = r
        if series != POP_SERIES or date != POP_DATE:
            continue
        if unit != UNIT:
            raise ScrapeError(f"{path}: line {k} ({jur}) has the unit {unit!r}, expected {UNIT}")
        if jur in found:
            raise ScrapeError(f"{path}: {POP_SERIES} for {jur} on {POP_DATE} appears twice")
        if not re.fullmatch(r"\d+", value):
            raise ScrapeError(f"{path}: line {k} ({jur}) has the population {value!r}, which is not a whole number")
        found[jur] = value
    missing = sorted(set(REGIONS.values()) - set(found))
    extra = sorted(set(found) - set(REGIONS.values()))
    if missing or extra:
        raise ScrapeError(f"{path} must have {POP_SERIES} on {POP_DATE} for all nine jurisdictions; missing {missing}" + (f", unexpected {extra}" if extra else ""))
    sha = hashlib.sha256(raw).hexdigest()
    log(f"Population on {POP_DATE} copied from metrics/{POP_SLUG}/data.csv (sha256 {sha}): Australia {found[NATIONAL]}.")
    return found, sha, len(raw)


# ---------------------------------------------------------------- the data file

def existing_counts(path):
    """{(series, jurisdiction): (row count, first date)} of an existing data.csv (empty if there is none)."""
    if not Path(path).exists():
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(Path(path).read_text(encoding="utf-8"))):
        k = (r["series"], r["jurisdiction"])
        n, first = out.get(k, (0, None))
        out[k] = (n + 1, r["date"] if first is None else min(first, r["date"]))
    return out


def build_csv(rows):
    """rows: dicts with the seven columns. Sorted by series, jurisdiction, then date, so the same figures
    always give the same bytes."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER.split(","))
    for r in sorted(rows, key=lambda r: (r["series"], r["jurisdiction"], r["date"])):
        w.writerow([r[c] for c in HEADER.split(",")])
    return buf.getvalue().encode("utf-8")


def round_half_up_fraction(f, decimals):
    """A Fraction rounded half away from zero to `decimals` places, as text."""
    scaled = f * 10 ** decimals
    n = (abs(scaled.numerator) * 2 + scaled.denominator) // (2 * scaled.denominator)
    n = -n if scaled < 0 else n
    sign = "-" if n < 0 else ""
    n = abs(n)
    return f"{sign}{n // 10 ** decimals}.{n % 10 ** decimals:0{decimals}d}" if decimals else f"{sign}{n}"


def worked_out(completions, population, first=ACCORD_FIRST_QUARTER, last=None):
    """The cumulative total since `first` to `last` (default: the latest quarter), and the rate per 1,000 residents,
    for one jurisdiction, worked out separately from the site's code (exact fractions).
    completions: {period: value text}; population: text. Returns (total int, rate text)."""
    last = last or max(completions)
    total, p = 0, first
    while True:
        if p not in completions:
            raise ScrapeError(f"the sum from {first} to {last} needs {p}, which is missing")
        total += int(completions[p])
        if p == last:
            break
        p = abs_.next_quarter(p)
    return total, round_half_up_fraction(Fraction(total) / Fraction(population) * 1000, 1)


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # ---- API: codes, names, series
    log(f"Downloading {API_URL}")
    raw_api = fetcher(API_URL, abs_.ACCEPT_SDMX)
    raw_labels = fetcher(API_URL, API_LABELS)
    names = sh.check_names(raw_labels, raw_api, label="the Building Activity response with labels", expect=LABEL_EXPECT, noun="Building Activity")
    log("Codes confirmed from the labelled response: " + ", ".join(f"{k} {v.split(': ', 1)[1]}" for k, v in LABEL_EXPECT.items()) + ".")
    log("Region names confirmed: " + ", ".join(f"{c} {names[c]}" for c in sorted(names, key=lambda c: (c == "AUS", c))) + ".")
    parts = sh.split_by_region(raw_api, label="the Building Activity response")
    api = {}
    for code, name in REGIONS.items():
        api[name] = abs_.parse_sdmx_series(parts[code], dict(EXPECTED, REGION=code), label=f"the ABS Building Activity response for {name}", freq="Q", blank_decimals=0)
    spans = {(s.pairs[0][0], s.pairs[-1][0], len(s.pairs)) for s in api.values()}
    if len(spans) != 1:
        raise ScrapeError(f"the nine regions do not cover the same quarters: {sorted(spans)}")
    first_q, last_q, n_q = next(iter(spans))
    log(f"API: {n_q} quarters per jurisdiction, {first_q} to {last_q}, none missing. Australia {last_q}: {dict(api[NATIONAL].pairs)[last_q]}.")

    # ---- workbooks: find the columns by header text and series type, check every quarter
    log(f"Looking for the time series workbooks on {PAGE_URL}")
    page = fetcher(PAGE_URL, "text/html")
    candidates = candidate_links(page, PAGE_URL)
    chosen, workbooks = find_columns(candidates, fetcher, log)
    checks, ids = {}, {}
    for name, (url, sheet, sid) in chosen.items():
        values = abs_.parse_spreadsheet_series(workbooks[url], sid, sheet=sheet, freq="Q", expected_meta=dict(SHEET_META, description_contains=SHEET_HEADERS[name]), label="the ABS Building Activity workbook")
        if set(values) != set(api[name].raw_values):
            only_api = sorted(set(api[name].raw_values) - set(values))
            only_sheet = sorted(set(values) - set(api[name].raw_values))
            raise ScrapeError(f"{name} (series {sid}): the API and the workbook cover different quarters: only in the API {only_api[:10]}, only in the workbook {only_sheet[:10]}")
        try:
            checks[name] = abs_.cross_check(api[name], values, log=lambda m: None, noun="quarter")
        except ScrapeError as e:
            raise ScrapeError(f"{name} (series {sid}): {e}") from None
        ids[name] = (url.rsplit("/", 1)[-1], sheet, sid)
        log(f"Cross-check {name} (series {sid}, {ids[name][0]}): {checks[name][0]} quarters agree ({checks[name][1]} to {checks[name][2]}); the latest quarter is {checks[name][2]} in both.")

    # ---- population copy
    pop, pop_sha, pop_bytes = read_population(root, log)

    # ---- rows
    rows = []
    for name, s in api.items():
        for period, value in s.pairs:
            rows.append({"date": abs_.quarter_end(period), "period": period, "series": "completions", "jurisdiction": name, "value": value, "unit": UNIT, "status": STATUS})
    for name, value in pop.items():
        rows.append({"date": POP_DATE, "period": POP_PERIOD, "series": OUT_POP, "jurisdiction": name, "value": value, "unit": UNIT, "status": STATUS})

    # ---- rows never fall
    data_path = root / "metrics" / SLUG / "data.csv"
    old = existing_counts(data_path)
    new = existing_counts_from_rows(rows)
    for k, (n, first) in old.items():
        if k not in new:
            raise ScrapeError(f"data.csv has {k[0]} ({k[1]}), which this run did not produce.")
        if new[k][0] < n:
            raise ScrapeError(f"{k[0]} ({k[1]}) now has {new[k][0]} rows, fewer than the {n} already in data.csv. Rows must never fall.")
        if new[k][1] > first:
            raise ScrapeError(f"{k[0]} ({k[1]}) now starts at {new[k][1]}, later than the {first} already in data.csv.")

    # ---- report what the site will work out (not stored)
    by_juris = {name: dict(s.pairs) for name, s in api.items()}
    summary = {}
    for name in REGIONS.values():
        summary[name] = worked_out(by_juris[name], pop[name])
    prior_last = abs_.previous_quarter(last_q)
    to_prior = worked_out(by_juris[NATIONAL], pop[NATIONAL], last=prior_last)
    q_index = 1
    p = ACCORD_FIRST_QUARTER
    while p != last_q:
        p = abs_.next_quarter(p)
        q_index += 1
    pace = round_half_up_fraction(Fraction(ACCORD_TARGET) * q_index / ACCORD_QUARTERS, 0)
    log(f"Worked out (not stored): Australia, {ACCORD_FIRST_QUARTER} to {prior_last}: {to_prior[0]} homes completed.")
    log(f"Worked out (not stored), {ACCORD_FIRST_QUARTER} to {last_q}: Australia {summary[NATIONAL][0]} homes, {summary[NATIONAL][1]} per 1,000 residents; straight-line pace {pace} ({q_index} of {ACCORD_QUARTERS} quarters).")
    for code, name in REGIONS.items():
        if name != NATIONAL:
            log(f"  {name}: {summary[name][0]} homes, {summary[name][1]} per 1,000 residents")

    # ---- nothing has failed: write everything
    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    files = [(API_NAME, API_URL, raw_api), (LABELS_NAME, API_URL, raw_labels)]
    files += [("abs-building-activity-" + url.rsplit("/", 1)[-1].lower(), url, raw) for url, raw in sorted(workbooks.items())]
    for name, url, raw in files:
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    # A reference, not a file in this folder: the validator does not look for it here.
    manifest[POP_MANIFEST_KEY] = {"path": f"metrics/{POP_SLUG}/data.csv", "series": POP_SERIES, "retrieved": retrieved, "sha256": pop_sha, "bytes": pop_bytes}
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(rows))
    log(f"Wrote metrics/{SLUG}/data.csv ({len(rows)} rows), saved the raw downloads and the manifest.")
    return {"api": api, "checks": checks, "ids": ids, "pop": pop, "summary": summary, "to_prior": to_prior, "pace": pace, "rows": rows, "pop_sha256": pop_sha}


def existing_counts_from_rows(rows):
    out = {}
    for r in rows:
        k = (r["series"], r["jurisdiction"])
        n, first = out.get(k, (0, None))
        out[k] = (n + 1, r["date"] if first is None else min(first, r["date"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download new homes completed (ABS Building Activity), copy the population from the social housing page, and write the data file.")
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
