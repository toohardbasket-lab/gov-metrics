#!/usr/bin/env python3
"""Rents scraper: three stored series, one metric folder (metrics/rents/).

1. rents_index_quarterly: the CPI rents index, eight capitals, original, quarterly, from the ABS Data
   API (CPI 1.115522.10.50.Q), from 1972-Q3. Stored exactly as the ABS gives it (at most two decimal
   places, never rounded; the DECIMALS cell is empty). Checked quarter by quarter against ABS Table 18
   (6401018.xlsx), series ID A2331876F.
2. rents_monthly, jurisdiction Australia: the published twelve-month change in rents from the monthly
   CPI, eight capitals (CPI 3.115522.10.50.M), from July 2023, one decimal place. Checked month by
   month against Table 3 (640103.xlsx), series ID A130390095C.
3. rents_monthly, one jurisdiction per capital city (CPI 3.115522.10.1+2+3+4+5+6+7+8.M). The REGION
   codes' names are confirmed from the same response asked for with labels (code: name) and must be
   1 Sydney, 2 Melbourne, 3 Brisbane, 4 Adelaide, 5 Perth, 6 Hobart, 7 Darwin, 8 Canberra. Each city is
   checked against Table 11 (6401011.xlsx): the sheet holds two Original columns with that city's header
   and different series IDs; both must hold the same figures and both must equal the API.

The quarterly twelve-month change (rents_quarterly) is NOT written here. The ABS does not publish it, so
the site works it out from the stored index at build time (derive in metric.yml). This scraper only
prints the latest worked-out figure, for the checking notes.

Run from anywhere:  python3 scrapers/rents.py

If any check fails (a non-200 answer, an unexpected code, a wrong region name, a repeated or missing
period, an unreadable value, a figure with too many decimal places, any cross-check disagreeing, the two
spreadsheet columns of a city disagreeing, the latest period differing, fewer rows than before) nothing is
written and the exit code is 1. Nothing is typed in: every figure comes from the downloaded bytes.
"""
import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from fractions import Fraction
from decimal import Decimal
from pathlib import Path

import abs_series as abs_
from abs_series import ScrapeError
from cpi_june import write_atomic

ROOT = Path(__file__).resolve().parents[1]
SLUG = "rents"

INDEX_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI/1.115522.10.50.Q"
MONTHLY_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI/3.115522.10.50.M"
CITIES_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI/3.115522.10.1+2+3+4+5+6+7+8.M"
LATEST_URL = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release"
TABLE18_ENDING = "/6401018.xlsx"
TABLE3_ENDING = "/640103.xlsx"
TABLE11_ENDING = "/6401011.xlsx"
ACCEPT_LABELS = "application/vnd.sdmx.data+csv;labels=both"

INDEX_NAME = "abs-cpi-1.115522.10.50.Q.csv"
MONTHLY_NAME = "abs-cpi-3.115522.10.50.M.csv"
CITIES_NAME = "abs-cpi-3.115522.10.1-8.M.csv"
CITIES_LABELS_NAME = "abs-cpi-3.115522.10.1-8.M-with-labels.csv"
TABLE18_NAME = "abs-cpi-6401018.xlsx"
TABLE3_NAME = "abs-cpi-640103.xlsx"
TABLE11_NAME = "abs-cpi-6401011.xlsx"

# Dimension codes that must be constant in each response (the same style as inflation.py).
EXPECTED_INDEX = {
    "DATAFLOW": lambda v: v.startswith("ABS:CPI("),
    "MEASURE": "1", "INDEX": "115522", "TSEST": "10", "REGION": "50", "FREQ": "Q", "UNIT_MEASURE": "IN",
}
EXPECTED_MONTHLY = {
    "DATAFLOW": lambda v: v.startswith("ABS:CPI("),
    "MEASURE": "3", "INDEX": "115522", "TSEST": "10", "REGION": "50", "FREQ": "M", "UNIT_MEASURE": "PCT",
}

# The REGION codes and what they must be called. The jurisdiction written to data.csv is the state or
# territory, using the full names; the city name is kept for display in metric.yml (state_panel_config).
REGIONS = {
    "1": ("Sydney", "New South Wales"),
    "2": ("Melbourne", "Victoria"),
    "3": ("Brisbane", "Queensland"),
    "4": ("Adelaide", "South Australia"),
    "5": ("Perth", "Western Australia"),
    "6": ("Hobart", "Tasmania"),
    "7": ("Darwin", "Northern Territory"),
    "8": ("Canberra", "Australian Capital Territory"),
}

# Spreadsheet series: the table, the series ID, and what the column must say about itself.
TABLE18_ID = "A2331876F"
TABLE18_META = {"description_contains": "Index Numbers ; Rents ; Australia ;", "Series Type": "Original", "Unit": "Index Numbers"}
TABLE3_ID = "A130390095C"
TABLE3_HEADER = "Percentage Change from Corresponding Month of Previous Year ; Rents ; Australia"
TABLE3_META = {"description_contains": TABLE3_HEADER, "Series Type": "Original", "Unit": "Percent"}
CITY_HEADER = "Percentage Change from Corresponding Month of Previous Year ; Rents ; {city} ;"
CITY_META_BASE = {"Series Type": "Original", "Unit": "Percent"}
COLUMNS_PER_CITY = 2

INDEX_DECIMALS = 2   # the index is accepted with at most two decimal places and never rounded
MONTHLY_DECIMALS = 1  # published percentage changes have one decimal place
LAG = 4              # the worked-out change compares a quarter with the one four quarters earlier

NATIONAL = "Australia"
STATUS = "actual"
HEADER = "date,period,series,jurisdiction,value,unit,status"
LABELS = {"rents_index_quarterly": "rents index (quarterly)", "rents_monthly": "rents, monthly CPI"}


# ---------------------------------------------------------------- the eight capitals in one response

def split_by_region(raw, label="the capital cities response"):
    """Splits an SDMX CSV response that holds several REGION codes into one CSV (bytes) per code.
    Refuses if the REGION column is missing, a row is malformed, or the codes found are not exactly
    the eight expected."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows or "REGION" not in rows[0]:
        raise ScrapeError(f"{label} lacks the column REGION; got {rows[0] if rows else None}")
    head = rows[0]
    k = head.index("REGION")
    groups = {}
    for n, r in enumerate(rows[1:], start=2):
        if len(r) != len(head):
            raise ScrapeError(f"{label}: line {n} has the wrong number of fields")
        groups.setdefault(r[k], []).append(r)
    if set(groups) != set(REGIONS):
        raise ScrapeError(f"{label} holds the REGION codes {sorted(groups)}; expected exactly {sorted(REGIONS)}")
    out = {}
    for code, grp in groups.items():
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(head)
        w.writerows(grp)
        out[code] = buf.getvalue().encode("utf-8")
    return out


def _cell_code_name(cell, where):
    """'2: Melbourne' -> ('2', 'Melbourne')."""
    code, sep, name = cell.partition(": ")
    if not sep:
        raise ScrapeError(f"{where}: {cell!r} is not in the form 'code: name'")
    return code.strip(), name.strip()


def check_region_names(raw_labels, raw_plain, label="the capital cities response with labels"):
    """The plain response only has codes. The same request made with labels gives 'code: name' in the
    REGION column. Every code must carry the expected name (1 Sydney ... 8 Canberra), and the labelled
    response must hold exactly the same figures as the plain one. Returns {code: name}."""
    try:
        text = raw_labels.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ScrapeError(f"{label} is empty")
    head = rows[0]

    def col(prefix):
        found = [i for i, h in enumerate(head) if h == prefix or h.startswith(prefix + ":")]
        if len(found) != 1:
            raise ScrapeError(f"{label}: expected one column {prefix}, found {len(found)}; got {head}")
        return found[0]

    c_region, c_time, c_val = col("REGION"), col("TIME_PERIOD"), col("OBS_VALUE")
    if head[c_region] != "REGION: Region":
        raise ScrapeError(f"{label}: the REGION column is headed {head[c_region]!r}, so it does not carry names")
    names, labelled = {}, {}
    for n, r in enumerate(rows[1:], start=2):
        if len(r) != len(head):
            raise ScrapeError(f"{label}: line {n} has the wrong number of fields")
        code, name = _cell_code_name(r[c_region], f"{label}: line {n}")
        if names.setdefault(code, name) != name:
            raise ScrapeError(f"{label}: REGION {code} is called both {names[code]!r} and {name!r}")
        key = (code, r[c_time])
        if key in labelled:
            raise ScrapeError(f"{label}: {code} {r[c_time]} appears twice")
        labelled[key] = r[c_val].strip()
    expected = {code: city for code, (city, _) in REGIONS.items()}
    if names != expected:
        diffs = [f"{c}: {names.get(c)!r} (expected {expected[c]!r})" for c in sorted(expected) if names.get(c) != expected[c]]
        extra = sorted(set(names) - set(expected))
        raise ScrapeError(f"the CPI region codes are not named as expected: {'; '.join(diffs)}"
                          + (f"; unexpected codes {extra}" if extra else ""))
    plain_rows = list(csv.DictReader(io.StringIO(raw_plain.decode("utf-8-sig"))))
    plain = {(r["REGION"], r["TIME_PERIOD"]): r["OBS_VALUE"].strip() for r in plain_rows}
    if plain != labelled:
        raise ScrapeError("the response with labels and the plain response do not hold the same figures")
    return names


# ---------------------------------------------------------------- the cross-checks

def check_same_periods(api_pairs, sheet_values, label, noun):
    """The API and the spreadsheet must cover the same periods (cross_check compares only the
    periods they share and the latest one)."""
    api, sheet = {p for p, _ in api_pairs}, set(sheet_values)
    if api != sheet:
        only_api, only_sheet = sorted(api - sheet), sorted(sheet - api)
        raise ScrapeError(f"{label}: the API and the spreadsheet cover different {noun}s. Only in the API: {only_api[:5]}; only in the spreadsheet: {only_sheet[:5]}")


def check_city(city, series, raw_sheet, log=print):
    """One city against Table 11. Finds the columns by header and series type, requires exactly two,
    requires the two to hold the same figures, and each to equal the API. Returns (ids, count, first, last)."""
    found = abs_.find_series_ids_by_header(raw_sheet, [CITY_HEADER.format(city=city)], series_type="Original", label="Table 11")
    if len(found) != COLUMNS_PER_CITY:
        raise ScrapeError(f"Table 11: {len(found)} Original columns have the header for {city}; expected exactly {COLUMNS_PER_CITY} (found {found})")
    ids = [sid for _, sid in found]
    if len(set(ids)) != len(ids):
        raise ScrapeError(f"Table 11: the series IDs for {city} are not different from each other: {ids}")
    meta = dict(CITY_META_BASE, description_contains=CITY_HEADER.format(city=city))
    cols = [abs_.parse_spreadsheet_series(raw_sheet, sid, sheet=sheet, expected_meta=meta, label="Table 11") for sheet, sid in found]
    # the two columns must hold the same months and the same figures (compared as the API would be, to its decimals)
    a, b = cols
    if set(a) != set(b):
        raise ScrapeError(f"Table 11: the two columns for {city} ({ids[0]}, {ids[1]}) cover different months")
    diff = [p for p in sorted(a) if abs_.round_half_up(a[p], MONTHLY_DECIMALS) != abs_.round_half_up(b[p], MONTHLY_DECIMALS)]
    if diff:
        shown = "; ".join(f"{p}: {ids[0]} {a[p]}, {ids[1]} {b[p]}" for p in diff[:10]) + (f"; and {len(diff) - 10} more" if len(diff) > 10 else "")
        raise ScrapeError(f"Table 11: the two columns for {city} disagree in {len(diff)} month(s): {shown}")
    results = []
    for sid, values in zip(ids, cols):
        check_same_periods(series.pairs, values, f"{city} (Table 11 {sid})", "month")
        try:
            results.append(abs_.cross_check(series, values, log=lambda m: None))
        except ScrapeError as e:
            raise ScrapeError(f"{city} (Table 11 series {sid}): {e}") from None
    log(f"Cross-check ({city}): {results[0][0]} months agree with both Table 11 columns {ids[0]} and {ids[1]} "
        f"({results[0][1]} to {results[0][2]}); the two columns also agree with each other; the latest month is {results[0][2]} in all three.")
    return ids, results[0][0], results[0][1], results[0][2]


def worked_out_change(index_pairs, lag=LAG):
    """The year-ended change worked out from the stored index, the way the site does it at build time:
    (index this quarter / index `lag` quarters earlier - 1) * 100, rounded half up to one decimal place.
    Exact (fractions, no floating point). A quarter with no index `lag` quarters earlier has no figure.
    Returns {period: (text, this index text, earlier index text)}."""
    index = {p: v for p, v in index_pairs}
    out = {}
    for p, v in index.items():
        prev = abs_.previous_quarter(p, lag)
        if prev not in index:
            continue
        a, b = Fraction(Decimal(v)), Fraction(Decimal(index[prev]))
        if b <= 0:
            continue
        tenths = (a / b - 1) * 1000  # the change in tenths of a point, exactly
        n = (abs(tenths.numerator) * 2 + tenths.denominator) // (2 * tenths.denominator)  # half away from zero
        text = f"{'-' if tenths < 0 and n else ''}{n // 10}.{n % 10}"
        out[p] = (text, v, index[prev])
    return out


# ---------------------------------------------------------------- the data file

def existing_counts(path: Path):
    """{(series, jurisdiction): (row count, first period)} of an existing data.csv (empty if there is none)."""
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        k = (r["series"], r["jurisdiction"])
        n, first = out.get(k, (0, None))
        out[k] = (n + 1, r["period"] if first is None else min(first, r["period"]))
    return out


def build_csv(groups):
    """groups: {(series, jurisdiction): (unit, [(period, value text)])}. Sorted by series, jurisdiction,
    then period, so the same figures always give the same bytes."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER.split(","))
    for (series, jur) in sorted(groups):
        unit, pairs = groups[(series, jur)]
        for period, value in sorted(pairs):
            date = abs_.quarter_end(period) if "-Q" in period else abs_.month_end(period)
            w.writerow([date, period, series, jur, value, unit, STATUS])
    return buf.getvalue().encode("utf-8")


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # Series 1: the quarterly index, and its check against Table 18
    log(f"Downloading {INDEX_URL}")
    raw_index = fetcher(INDEX_URL, abs_.ACCEPT_SDMX)
    index = abs_.parse_sdmx_series(raw_index, EXPECTED_INDEX, label="the ABS rents index response", freq="Q", blank_decimals=INDEX_DECIMALS)
    log(f"Rents index: {len(index.pairs)} quarters, {index.pairs[0][0]} to {index.pairs[-1][0]}, none missing. Latest value {index.pairs[-1][1]}.")

    # Series 2: the monthly change for the eight capitals
    log(f"Downloading {MONTHLY_URL}")
    raw_monthly = fetcher(MONTHLY_URL, abs_.ACCEPT_SDMX)
    monthly = abs_.parse_sdmx_series(raw_monthly, EXPECTED_MONTHLY, label="the ABS monthly rents response", freq="M", blank_decimals=MONTHLY_DECIMALS)
    log(f"Rents, monthly: {len(monthly.pairs)} months, {monthly.pairs[0][0]} to {monthly.pairs[-1][0]}, none missing. Latest value {monthly.pairs[-1][1]}.")

    # Series 3: the eight capital cities, with the region names confirmed
    log(f"Downloading {CITIES_URL}")
    raw_cities = fetcher(CITIES_URL, abs_.ACCEPT_SDMX)
    log(f"Downloading {CITIES_URL} again, asking for labels, to confirm the region names")
    raw_labels = fetcher(CITIES_URL, ACCEPT_LABELS)
    names = check_region_names(raw_labels, raw_cities)
    log("Region names confirmed: " + ", ".join(f"{c} {names[c]}" for c in sorted(names)) + ".")
    parts = split_by_region(raw_cities)
    cities = {}
    for code in sorted(REGIONS):
        expected = dict(EXPECTED_MONTHLY, REGION=code)
        cities[code] = abs_.parse_sdmx_series(parts[code], expected, label=f"the ABS monthly rents response for {REGIONS[code][0]}",
                                              freq="M", blank_decimals=MONTHLY_DECIMALS)
        c = cities[code]
        log(f"  {REGIONS[code][0]} ({REGIONS[code][1]}): {len(c.pairs)} months, {c.pairs[0][0]} to {c.pairs[-1][0]}, none missing. Latest value {c.pairs[-1][1]}.")
    spans = {(c.pairs[0][0], c.pairs[-1][0], len(c.pairs)) for c in cities.values()}
    if len(spans) != 1:
        raise ScrapeError(f"the eight capitals do not cover the same months: {sorted(spans)}")

    # The spreadsheets
    log(f"Looking for the current table links on {LATEST_URL}")
    page = fetcher(LATEST_URL, "text/html")
    urls = {name: abs_.find_link(page, LATEST_URL, ending) for name, ending in
            (("18", TABLE18_ENDING), ("3", TABLE3_ENDING), ("11", TABLE11_ENDING))}
    raw_sheets = {}
    for name in ("18", "3", "11"):
        log(f"Downloading {urls[name]}")
        raw_sheets[name] = fetcher(urls[name], "*/*")

    # Table 18 against the index
    t18 = abs_.parse_spreadsheet_series(raw_sheets["18"], TABLE18_ID, freq="Q", expected_meta=TABLE18_META, label="Table 18")
    log(f"Table 18 column {TABLE18_ID}: {len(t18)} quarters, {min(t18)} to {max(t18)}.")
    check_same_periods(index.pairs, t18, "Table 18", "quarter")
    index_check = abs_.cross_check(index, t18, log, noun="quarter")

    # Table 3 against the national monthly figure
    t3 = abs_.parse_spreadsheet_series(raw_sheets["3"], TABLE3_ID, freq="M", expected_meta=TABLE3_META, label="Table 3")
    log(f"Table 3 column {TABLE3_ID}: {len(t3)} months, {min(t3)} to {max(t3)}.")
    check_same_periods(monthly.pairs, t3, "Table 3", "month")
    monthly_check = abs_.cross_check(monthly, t3, log, noun="month")

    # Table 11 against each city
    city_checks = {}
    for code in sorted(REGIONS):
        city = REGIONS[code][0]
        city_checks[city] = check_city(city, cities[code], raw_sheets["11"], log)

    # The worked-out quarterly change: printed for the checking notes only, never stored
    worked = worked_out_change(index.pairs)
    last = max(worked)
    log(f"Worked out from the index (not stored): {len(worked)} quarters, {min(worked)} to {last}. "
        f"Latest {last}: {worked[last][0]} = ({worked[last][1]} / {worked[last][2]} - 1) x 100, the two index values being {last} and {abs_.previous_quarter(last, LAG)}.")

    groups = {("rents_index_quarterly", NATIONAL): ("index", index.pairs), ("rents_monthly", NATIONAL): ("pct", monthly.pairs)}
    for code, (city, state) in REGIONS.items():
        groups[("rents_monthly", state)] = ("pct", cities[code].pairs)

    # Rows never fall
    data_path = root / "metrics" / SLUG / "data.csv"
    old = existing_counts(data_path)
    for key, (unit, pairs) in groups.items():
        if key in old:
            old_count, old_first = old[key]
            if len(pairs) < old_count:
                raise ScrapeError(f"{key[0]} ({key[1]}) now has {len(pairs)} rows, fewer than the {old_count} already in data.csv. Rows must never fall.")
            if pairs[0][0] > old_first:
                raise ScrapeError(f"{key[0]} ({key[1]}) now starts at {pairs[0][0]}, later than the {old_first} already in data.csv.")
    for key in old:
        if key not in groups:
            raise ScrapeError(f"data.csv has {key[0]} ({key[1]}), which this run did not produce.")

    # Nothing has failed: write everything.
    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    manifest_path = sources / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for name, url, raw in ((INDEX_NAME, INDEX_URL, raw_index), (MONTHLY_NAME, MONTHLY_URL, raw_monthly), (CITIES_NAME, CITIES_URL, raw_cities),
                           (CITIES_LABELS_NAME, CITIES_URL, raw_labels), (TABLE18_NAME, urls["18"], raw_sheets["18"]),
                           (TABLE3_NAME, urls["3"], raw_sheets["3"]), (TABLE11_NAME, urls["11"], raw_sheets["11"])):
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(groups))
    total = sum(len(p) for _, p in groups.values())
    log(f"Wrote metrics/{SLUG}/data.csv ({total} rows), saved all seven raw downloads and the manifest.")
    return {"index": index.pairs, "monthly": monthly.pairs, "cities": {REGIONS[c][0]: cities[c].pairs for c in cities},
            "index_check": index_check, "monthly_check": monthly_check, "city_checks": city_checks, "worked": worked,
            "urls": urls}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download Australian rents figures and write their data file.")
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
