#!/usr/bin/env python3
"""Social housing scraper: five stored series, one metric folder (metrics/social-housing/).

Dwellings at 30 June, from the Productivity Commission's Report on Government Services (RoGS), section 18
(housing), table 18A.3, Measure "Descriptive data", read with scrapers/rogs.py from the Commission's CSV
and checked figure by figure against its Excel tables:
  public_housing                 Description1 "Public housing"
  somih                          Description1 "State owned and managed Indigenous housing"
  community_housing              Description1 "Community housing", Description3 "Number of Tenancy (Rental) Units"
                                 (tenancy units, not "Number of dwellings": the Commission's national total uses them)
  indigenous_community_housing   Description1 "Indigenous community housing"
Population, series `population`: ABS estimated resident population at 30 June (June quarter), persons, all
ages, Australia and each state and territory, from the ABS Data API (ERP_Q 1.3.TOT.<region>.Q), checked
against the ABS time series spreadsheet of the same figures (found by its column headers).

The total and the rate per 1,000 people are NOT written here. The site works them out at build time
(derive in metric.yml). This scraper only prints them, worked out separately in Python, for the checking notes.

Codes in the Commission's tables (.., na, np, nil) are stored as codes in data.csv; the metric decides what they mean.

History: each RoGS edition carries only ten years. Dwelling rows already stored for years the new edition no
longer carries are kept unchanged; years in both come from the new edition (the checker's revision test then
decides whether a changed figure is accepted). sources/manifest.json records, in an "rogs-editions" entry,
the edition each stored year last came from.

Run from anywhere:  python3 scrapers/social_housing.py

If any check fails nothing is written and the exit code is 1.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from urllib.parse import urljoin, urlparse

import abs_series as abs_
import rogs
from abs_series import ScrapeError
from cpi_june import write_atomic

ROOT = Path(__file__).resolve().parents[1]
SLUG = "social-housing"

TABLE = "18A.3"
MEASURE = "Descriptive data"
CSV_SLUG = "section18-housing-dataset"
XLSX_SLUG = "section18-housing-data-tables"
FIRST_YEAR = 2016
EDITIONS_KEY = "rogs-editions"

SELECTIONS = {
    "public_housing": {"Description1": "Public housing"},
    "somih": {"Description1": "State owned and managed Indigenous housing"},
    "community_housing": {"Description1": "Community housing", "Description3": "Number of Tenancy (Rental) Units"},
    "indigenous_community_housing": {"Description1": "Indigenous community housing"},
}
DWELLING_SERIES = list(SELECTIONS)

# The jurisdiction names written to data.csv: the same scheme as metrics/rents.
JURISDICTION = {"NSW": "New South Wales", "Vic": "Victoria", "Qld": "Queensland", "WA": "Western Australia", "SA": "South Australia",
                "Tas": "Tasmania", "ACT": "Australian Capital Territory", "NT": "Northern Territory", "Aust": "Australia"}
NATIONAL = "Australia"

ERP_URL = "https://data.api.abs.gov.au/rest/data/ABS,ERP_Q/1.3.TOT.AUS+1+2+3+4+5+6+7+8.Q"
ERP_LABELS = "application/vnd.sdmx.data+csv;labels=both"
POP_PAGE = "https://www.abs.gov.au/statistics/people/population/national-state-and-territory-population/latest-release"
# The ERP REGION codes and what they must be called (confirmed from the labelled response).
REGIONS = {"1": "New South Wales", "2": "Victoria", "3": "Queensland", "4": "South Australia", "5": "Western Australia",
           "6": "Tasmania", "7": "Northern Territory", "8": "Australian Capital Territory", "AUS": "Australia"}
EXPECTED_ERP = {"DATAFLOW": lambda v: v.startswith("ABS:ERP_Q("), "MEASURE": "1", "SEX": "3", "AGE": "TOT", "FREQ": "Q", "UNIT_MEASURE": "PSNS"}
LABEL_EXPECT = {"MEASURE": "1: Estimated Resident Population", "SEX": "3: Persons", "AGE": "TOT: All ages"}
SHEET_HEADER = "Estimated Resident Population ; Persons ; {name} ;"
SHEET_META = {"Series Type": "Original", "Unit": "Persons"}
SHEET_NAME_RE = re.compile(r"^3101\d+[A-Za-z]?\.xlsx$", re.I)

HEADER = "date,period,series,jurisdiction,value,unit,status"
STATUS = "actual"
UNIT = "count"


# ---------------------------------------------------------------- population

def split_by_region(raw, label="the population response"):
    """Splits an SDMX CSV response with several REGION codes into one CSV (bytes) per code; the codes must
    be exactly the nine expected."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "REGION" not in rows[0]:
        raise ScrapeError(f"{label} lacks the column REGION; got {rows[0] if rows else None}")
    head, k = rows[0], rows[0].index("REGION")
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


def check_names(raw_labels, raw_plain, label="the population response with labels", expect=None, noun="population"):
    """The same request made with labels gives 'code: name' cells. Every region code must carry the expected
    name, the other dimensions must be the expected ones (`expect`: column -> 'code: name'; the default is the
    population's measure, sex and age), and the labelled response must hold exactly the same figures as the
    plain one. `noun` only words the messages. Returns {code: name}."""
    expect = LABEL_EXPECT if expect is None else expect
    try:
        rows = list(csv.reader(io.StringIO(raw_labels.decode("utf-8-sig"))))
    except UnicodeDecodeError as e:
        raise ScrapeError(f"{label} is not text: {e}") from None
    if not rows:
        raise ScrapeError(f"{label} is empty")
    head = rows[0]

    def col(prefix):
        found = [i for i, h in enumerate(head) if h == prefix or h.startswith(prefix + ":")]
        if len(found) != 1:
            raise ScrapeError(f"{label}: expected one column {prefix}, found {len(found)}; got {head}")
        return found[0]

    c_reg, c_time, c_val = col("REGION"), col("TIME_PERIOD"), col("OBS_VALUE")
    names, labelled, constant = {}, {}, {}
    for n, r in enumerate(rows[1:], start=2):
        if len(r) != len(head):
            raise ScrapeError(f"{label}: line {n} has the wrong number of fields")
        code, sep, name = r[c_reg].partition(": ")
        if not sep:
            raise ScrapeError(f"{label}: line {n}: {r[c_reg]!r} is not in the form 'code: name'")
        if names.setdefault(code, name.strip()) != name.strip():
            raise ScrapeError(f"{label}: REGION {code} is called both {names[code]!r} and {name!r}")
        for key in expect:
            constant.setdefault(key, set()).add(r[col(key)])
        key = (code, r[c_time])
        if key in labelled:
            raise ScrapeError(f"{label}: {code} {r[c_time]} appears twice")
        labelled[key] = r[c_val].strip()
    if names != REGIONS:
        diffs = [f"{c}: {names.get(c)!r} (expected {REGIONS[c]!r})" for c in sorted(REGIONS) if names.get(c) != REGIONS[c]]
        raise ScrapeError(f"the {noun} region codes are not named as expected: {'; '.join(diffs)}")
    for key, want in expect.items():
        if constant.get(key) != {want}:
            raise ScrapeError(f"{label}: {key} is {sorted(constant.get(key, []))}, expected only {want!r}")
    plain = {(r["REGION"], r["TIME_PERIOD"]): r["OBS_VALUE"].strip() for r in csv.DictReader(io.StringIO(raw_plain.decode("utf-8-sig")))}
    if plain != labelled:
        raise ScrapeError("the response with labels and the plain response do not hold the same figures")
    return names


def sheet_links(html_bytes, page_url):
    """Every link on the ABS page to a time series workbook (a file named 3101....xlsx), as full https
    addresses on www.abs.gov.au."""
    found = []
    for m in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html_bytes.decode("utf-8", errors="replace"), re.I):
        href = m.group(1).strip().split("#")[0].split("?")[0]
        if SHEET_NAME_RE.match(href.rsplit("/", 1)[-1]):
            full = urljoin(page_url, href)
            u = urlparse(full)
            if u.scheme != "https" or u.hostname != "www.abs.gov.au":
                raise ScrapeError(f"the link {full} is not an https address on www.abs.gov.au")
            if full not in found:
                found.append(full)
    if not found:
        raise ScrapeError(f"no link to a 3101....xlsx workbook was found on {page_url}")
    return found


def sheet_ids(raw):
    """If this workbook holds the quarterly persons figures for all nine jurisdictions, {jurisdiction: (sheet, series ID)}; else None.
    Each header must match exactly one Original column."""
    out = {}
    try:
        for name in REGIONS.values():
            found = abs_.find_series_ids_by_header(raw, [SHEET_HEADER.format(name=name)], series_type="Original", label="the ABS workbook")
            if len(found) == 0:
                return None
            if len(found) > 1:
                raise ScrapeError(f"the header for {name} matches {len(found)} columns {found}")
            out[name] = found[0]
    except ScrapeError as e:
        if "could not be opened" in str(e) or "has no Data sheets" in str(e) or "Series ID" in str(e):
            return None
        raise
    return out


def find_population_workbook(links, fetcher, log=print):
    """Downloads each candidate workbook and keeps the one whose column headers are the quarterly persons
    ERP of every state, territory and Australia. Refuses if none, or more than one, has them.
    Returns (url, raw bytes, {jurisdiction: (sheet, series ID)})."""
    hits = []
    for url in links:
        raw = fetcher(url, "*/*")
        ids = sheet_ids(raw)
        log(f"  {url.rsplit('/', 1)[-1]}: {'has the quarterly persons ERP headers' if ids else 'not the population table'}")
        if ids:
            hits.append((url, raw, ids))
    if len(hits) != 1:
        raise ScrapeError(f"{len(hits)} workbooks on the ABS page have the quarterly persons ERP columns; expected exactly one")
    return hits[0]


# ---------------------------------------------------------------- the data file

def read_csv_rows(path):
    if not Path(path).exists():
        return []
    return list(csv.DictReader(io.StringIO(Path(path).read_text(encoding="utf-8"))))


def build_csv(rows):
    """rows: dicts with the seven columns. Sorted by series, jurisdiction, then date."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER.split(","))
    for r in sorted(rows, key=lambda r: (r["series"], r["jurisdiction"], r["date"])):
        w.writerow([r[c] for c in HEADER.split(",")])
    return buf.getvalue().encode("utf-8")


def worked_out(parts_by_series, population, factor=1000, decimals=1):
    """The total and the rate for one jurisdiction and year, worked out separately from the site's code
    (exact fractions). parts: four cell texts; population: text. Returns (total text or None, rate text or None)."""
    total, unknown = Fraction(0), False
    for p in parts_by_series:
        if p in ("..", "-"):
            continue
        if p in ("na", "np"):
            unknown = True
            continue
        total += Fraction(Decimal(p))
    if unknown:
        return None, None
    if population in rogs.CODES:
        return str(int(total)), None
    r = total / Fraction(Decimal(population)) * factor * 10 ** decimals
    n = (abs(r.numerator) * 2 + r.denominator) // (2 * r.denominator)  # half away from zero
    return str(int(total)), f"{n // 10 ** decimals}.{n % 10 ** decimals:0{decimals}d}"


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # ---- RoGS: find, download, read, cross-check
    log(f"Looking for the RoGS files on {rogs.FRONT_URL}")
    found = rogs.discover(fetcher, [CSV_SLUG, XLSX_SLUG], log=log)
    csv_url, xlsx_url = found.files[CSV_SLUG], found.files[XLSX_SLUG]
    log(f"RoGS edition {found.edition}" + (f" (the {found.fell_back_from} edition does not have the housing section yet)" if found.fell_back_from else "") + f": {csv_url}")
    raw_csv = fetcher(csv_url, "*/*")
    raw_xlsx = fetcher(xlsx_url, "*/*")
    ds = rogs.parse_dataset(raw_csv)
    base = {"Table_Number": TABLE, "Measure": MEASURE}
    table_years = rogs.years_of(ds, base)
    if not table_years or not all(rogs.YEAR_RE.fullmatch(y) and len(y) == 4 for y in table_years):
        raise ScrapeError(f"the years of table {TABLE} are not calendar years: {table_years}")
    years = [y for y in table_years if int(y) >= FIRST_YEAR]
    if not years:
        raise ScrapeError(f"table {TABLE} has no year from {FIRST_YEAR}")
    wb_rows = rogs.read_workbook(raw_xlsx, TABLE)
    selected, checked = {}, {}
    for sid, extra in SELECTIONS.items():
        where = {**base, **extra}
        selected[sid] = rogs.select(ds, where, years, label=f"the RoGS CSV, {sid}")
        unit = rogs.units_of(ds, where, set(years))
        if unit != "no.":
            raise ScrapeError(f"{sid}: the unit is {unit!r}, expected 'no.' (a count of dwellings)")
        checked[sid] = rogs.cross_check(selected[sid], wb_rows, rogs.description_path(where), label=f"the RoGS workbook, {sid}")
        log(f"Cross-check {sid}: {checked[sid]} figures ({len(years)} years x {len(rogs.JURISDICTIONS)} columns) agree between the CSV and the workbook.")
    rogs_total = sum(checked.values())
    log(f"RoGS table {TABLE}: {rogs_total} of {rogs_total} figures agree between the CSV and the workbook; years {years[0]} to {years[-1]}.")

    # ---- ERP: API, region names, spreadsheet
    log(f"Downloading {ERP_URL}")
    raw_erp = fetcher(ERP_URL, abs_.ACCEPT_SDMX)
    raw_labels = fetcher(ERP_URL, ERP_LABELS)
    names = check_names(raw_labels, raw_erp)
    log("Region names confirmed: " + ", ".join(f"{c} {names[c]}" for c in sorted(names, key=lambda c: (c == "AUS", c))) + ".")
    parts = split_by_region(raw_erp)
    pop = {}
    for code, name in REGIONS.items():
        pop[name] = abs_.parse_sdmx_series(parts[code], dict(EXPECTED_ERP, REGION=code), label=f"the ABS population response for {name}", freq="Q", blank_decimals=0)
    spans = {(s.pairs[0][0], s.pairs[-1][0], len(s.pairs)) for s in pop.values()}
    if len(spans) != 1:
        raise ScrapeError(f"the nine regions do not cover the same quarters: {sorted(spans)}")
    log(f"Population (API): {len(next(iter(pop.values())).pairs)} quarters per region, {min(spans)[0]} to {min(spans)[1]}, none missing.")
    log(f"Looking for the population workbook on {POP_PAGE}")
    page = fetcher(POP_PAGE, "text/html")
    pop_url, raw_pop_xlsx, ids = find_population_workbook(sheet_links(page, POP_PAGE), fetcher, log)
    log(f"Population workbook: {pop_url}")
    erp_checks = {}
    for name, (sheet, sid) in ids.items():
        meta = dict(SHEET_META, description_contains=SHEET_HEADER.format(name=name))
        values = abs_.parse_spreadsheet_series(raw_pop_xlsx, sid, sheet=sheet, freq="Q", expected_meta=meta, label="the ABS population workbook")
        api_q = {p for p, _ in pop[name].pairs}
        # the workbook may reach back further than the API; it must not lack a quarter of the API's or add one after its start
        extra = {p for p in set(values) - api_q if p > min(api_q)}
        if not api_q <= set(values) or extra:
            raise ScrapeError(f"{name}: the API and the workbook cover different quarters (only in the API: {sorted(api_q - set(values))[:5]}; only in the workbook: {sorted(extra)[:5]})")
        values = {p: v for p, v in values.items() if p in api_q}
        try:
            erp_checks[name] = abs_.cross_check(pop[name], values, log=lambda m: None, noun="quarter")
        except ScrapeError as e:
            raise ScrapeError(f"population, {name} (series {sid}): {e}") from None
        june_ok = sum(1 for p, v in pop[name].pairs if p.endswith("-Q2") and abs_.round_half_up(values[p], 0) == v)
        log(f"Cross-check population, {name} (series {sid}): {erp_checks[name][0]} quarters agree ({erp_checks[name][1]} to {erp_checks[name][2]}), including {june_ok} June quarters.")
    june_total = sum(1 for s in pop.values() for p, _ in s.pairs if p.endswith("-Q2"))

    # ---- rows
    new_rows = []
    for sid, cells_by_year in selected.items():
        for y, cells in cells_by_year.items():
            for col, text in cells.items():
                new_rows.append({"date": f"{y}-06-30", "period": y, "series": sid, "jurisdiction": JURISDICTION[col], "value": text, "unit": UNIT, "status": STATUS})
    pop_rows = []
    for name, s in pop.items():
        for p, v in s.pairs:
            y = int(p[:4])
            if p.endswith("-Q2") and y >= FIRST_YEAR:
                pop_rows.append({"date": f"{y}-06-30", "period": str(y), "series": "population", "jurisdiction": name, "value": v, "unit": UNIT, "status": STATUS})
    pop_years = sorted({r["period"] for r in pop_rows})
    if not pop_years or pop_years[0] != str(FIRST_YEAR):
        raise ScrapeError(f"the population has June quarters {pop_years[:1]}..{pop_years[-1:]}; expected to start at {FIRST_YEAR}")
    # the dwellings and the population cover the same years
    if pop_years != years:
        log(f"Note: dwellings cover {years[0]} to {years[-1]} and the population {pop_years[0]} to {pop_years[-1]}.")

    # ---- history
    data_path = root / "metrics" / SLUG / "data.csv"
    manifest_path = root / "metrics" / SLUG / "sources" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    old_all = read_csv_rows(data_path)
    old_dwellings = [r for r in old_all if r["series"] in DWELLING_SERIES]
    old_editions = (manifest.get(EDITIONS_KEY) or {}).get("editions", {})
    dwellings, editions = rogs.merge_history(old_dwellings, new_rows, set(years), found.edition, old_editions)
    kept = len(dwellings) - len(new_rows)
    if kept:
        log(f"Kept {kept} stored rows for years the {found.edition} edition no longer carries (unchanged).")
    all_rows = dwellings + pop_rows
    key_count = lambda rows: {k: sum(1 for r in rows if (r["series"], r["jurisdiction"]) == k) for k in {(r["series"], r["jurisdiction"]) for r in rows}}  # noqa: E731
    new_counts, old_counts = key_count(all_rows), key_count(old_all)
    for k, n in old_counts.items():
        if new_counts.get(k, 0) < n:
            raise ScrapeError(f"{k[0]} ({k[1]}) now has {new_counts.get(k, 0)} rows, fewer than the {n} already in data.csv. Rows must never fall.")

    # ---- report what the site will work out (not stored)
    stored = {(r["series"], r["jurisdiction"], r["period"]): r["value"] for r in all_rows}
    latest = max(years)
    summary = {}
    for col, jur in JURISDICTION.items():
        sums = worked_out([stored[(s, jur, latest)] for s in DWELLING_SERIES], stored[("population", jur, latest)])
        summary[jur] = sums
    na, rates = summary[NATIONAL]
    log(f"Worked out (not stored), {latest}: Australia total {na} social housing dwellings; {rates} per 1,000 people (population {stored[('population', NATIONAL, latest)]}).")
    for col, jur in JURISDICTION.items():
        if jur != NATIONAL:
            log(f"  {jur}: total {summary[jur][0]}, per 1,000 people {summary[jur][1]}")
    somih_dots = sorted({JURISDICTION[c] for y in years for c, t in selected["somih"][y].items() if t == ".."})
    log(f"State owned and managed Indigenous housing is '..' (not applicable) for: {', '.join(somih_dots)}.")

    # ---- nothing has failed: write everything
    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    files = [(csv_url.split("?")[0].rsplit("/", 1)[-1], csv_url, raw_csv), (xlsx_url.split("?")[0].rsplit("/", 1)[-1], xlsx_url, raw_xlsx),
             ("abs-erp_q-1.3.TOT.1-8-AUS.Q.csv", ERP_URL, raw_erp), ("abs-erp_q-1.3.TOT.1-8-AUS.Q-with-labels.csv", ERP_URL, raw_labels),
             ("abs-erp-" + pop_url.rsplit("/", 1)[-1].lower(), pop_url, raw_pop_xlsx)]
    for name, url, raw in files:
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    manifest[EDITIONS_KEY] = {"editions": editions}
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(all_rows))
    log(f"Wrote metrics/{SLUG}/data.csv ({len(all_rows)} rows), saved the raw downloads and the manifest.")
    return {"years": years, "selected": selected, "checked": checked, "pop": pop, "erp_checks": erp_checks, "june_total": june_total,
            "summary": summary, "editions": editions, "rows": all_rows, "edition": found.edition}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download social housing and population figures and write their data file.")
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
