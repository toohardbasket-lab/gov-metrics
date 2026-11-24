#!/usr/bin/env python3
"""Homelessness scraper: seven stored series, one metric folder (metrics/homelessness/).

From the Productivity Commission's Report on Government Services (RoGS), section 19 (homelessness services), read
with scrapers/rogs.py from the Commission's CSV and checked figure by figure against its Excel tables. Each series is
picked by exact matches on named CSV columns (a table number always among them):

Census series, table 19A.2 (Measure "Homelessness; by homelessness operational group", Description1 "People who are
homeless by operational group", Description4 "Total"), one figure per Census (2011, 2016, 2021):
  census_homeless_rate    Description3 "Rate per 10000 people in the population", Unit "rate", one decimal
  census_homeless_number  Description3 "Number", Unit "no.", whole numbers
Service series, financial years 2020-21 onwards:
  clients                       table 19A.10, Measure "Unmet need", Description1 "Total clients", Unit "no."
  unmet_accommodation_pct       table 19A.10, Description1 "Accommodation services", Description3 "Proportion of clients
                                with unmet need", Unit "%", one decimal
  unassisted_accommodation_daily, unassisted_other_daily, unassisted_no_need_daily
                                table 19A.11, Measure "Unassisted requests", Description3 "Average daily unassisted
                                requests", Description1 "Accommodation services", "Services other than accommodation",
                                "No service need identified"; Unit "no.", one decimal (unit written: per_day)
The total of the three daily series is worked out by the site, not stored.

Dates. A Census is dated its Census night (CENSUS_NIGHT below, keyed by the year) and keeps the year as its period. A
Census year that is not in that map is refused, so a 2026 Census in a later edition stops the update until someone adds
its date. A financial year is dated 30 June of its second year and keeps the Commission's label ("2024-25").

Figures are stored exactly as published (the number of decimal places is checked; the Commission prints a true zero as
a plain 0 in the one-decimal table 19A.11, which is accepted and stored as published). Codes in the Commission's tables
(.., na, np, -) are stored as codes.

History: each RoGS edition carries only some years. Rows already stored for years the new edition no longer carries are
kept unchanged; years in both come from the new edition (the checker's revision test then decides whether a changed past
figure is accepted). sources/manifest.json records, in a "rogs-editions" entry, the edition each stored period last came from.

Run from anywhere:  python3 scrapers/homelessness.py

If any check fails nothing is written and the exit code is 1.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import abs_series as abs_
import rogs
from abs_series import ScrapeError
from cpi_june import write_atomic
from hospital_waits import JURISDICTION, NATIONAL, STATUS, build_csv, check_decimals, check_years, financial_year, read_csv_rows

ROOT = Path(__file__).resolve().parents[1]
SLUG = "homelessness"

CSV_SLUG = "section19-homelessness-services-dataset"
XLSX_SLUG = "section19-homelessness-services-data-tables"
FIRST_YEAR = 2020  # the first year of the first financial year kept (2020-21)
EDITIONS_KEY = "rogs-editions"

# Census night of each Census, keyed by the year the Commission uses. A Census year that is not here is refused.
CENSUS_NIGHT = {"2011": "2011-08-09", "2016": "2016-08-09", "2021": "2021-08-10"}
CENSUS_GAP_YEARS = 5

MEASURE_CENSUS = "Homelessness; by homelessness operational group"
CENSUS_WHERE = {"Measure": MEASURE_CENSUS, "Description1": "People who are homeless by operational group", "Description4": "Total"}
UNASSISTED_WHERE = {"Measure": "Unassisted requests", "Description3": "Average daily unassisted requests", "Unit": "no."}

# One entry per stored series. `kind` is "census" or "service". `where` are the exact CSV column matches. `unit` is
# the unit written to data.csv. `workbook` is the row labels above the figure in the Excel table (footnote marks
# removed). `decimals` is the number of decimal places the Commission prints; every figure (not a code) must have
# exactly that many.
SERIES = {
    "census_homeless_rate": {
        "kind": "census", "table": "19A.2", "unit": "rate", "decimals": 1,
        "where": {**CENSUS_WHERE, "Description3": "Rate per 10000 people in the population", "Unit": "rate"},
        "workbook": ("Rate per 10,000 people in the population", "Total"),
    },
    "census_homeless_number": {
        "kind": "census", "table": "19A.2", "unit": "count", "decimals": 0,
        "where": {**CENSUS_WHERE, "Description3": "Number", "Unit": "no."},
        "workbook": ("Number", "Total"),
    },
    "clients": {
        "kind": "service", "table": "19A.10", "unit": "count", "decimals": 0,
        "where": {"Measure": "Unmet need", "Description1": "Total clients", "Unit": "no."},
        "workbook": ("Total clients",),
    },
    "unmet_accommodation_pct": {
        "kind": "service", "table": "19A.10", "unit": "pct", "decimals": 1,
        "where": {"Measure": "Unmet need", "Description1": "Accommodation services", "Description3": "Proportion of clients with unmet need", "Unit": "%"},
        "workbook": ("Accommodation services", "Proportion of clients with unmet need"),
    },
    "unassisted_accommodation_daily": {
        "kind": "service", "table": "19A.11", "unit": "per_day", "decimals": 1,
        "where": {**UNASSISTED_WHERE, "Description1": "Accommodation services"},
        "workbook": ("Average daily unassisted requests", "Accommodation services"),
    },
    "unassisted_other_daily": {
        "kind": "service", "table": "19A.11", "unit": "per_day", "decimals": 1,
        "where": {**UNASSISTED_WHERE, "Description1": "Services other than accommodation"},
        "workbook": ("Average daily unassisted requests", "Services other than accommodation"),
    },
    "unassisted_no_need_daily": {
        "kind": "service", "table": "19A.11", "unit": "per_day", "decimals": 1,
        "where": {**UNASSISTED_WHERE, "Description1": "No service need identified"},
        "workbook": ("Average daily unassisted requests", "No service need identified"),
    },
}

CENSUS_RE = re.compile(r"\d{4}")


# ---------------------------------------------------------------- dates

def census_date(year):
    """'2021' -> '2021-08-10', Census night. Refuses a year that is not in CENSUS_NIGHT (a new Census has no date yet)."""
    if not CENSUS_RE.fullmatch(year):
        raise ScrapeError(f"the year {year!r} is not a Census year such as 2021")
    if year not in CENSUS_NIGHT:
        raise ScrapeError(f"the Census year {year} is not in CENSUS_NIGHT in scrapers/homelessness.py, so its Census night is not known. Add its date there once the ABS has published it, then run again.")
    return CENSUS_NIGHT[year]


def check_census_years(years):
    """Censuses are five years apart, with no Census missing."""
    ys = [int(y) for y in years]
    if any(b - a != CENSUS_GAP_YEARS for a, b in zip(ys, ys[1:])):
        raise ScrapeError(f"the Census years {years} are not {CENSUS_GAP_YEARS} years apart")


def date_of(kind, year):
    return census_date(year) if kind == "census" else financial_year(year)[1]


# ---------------------------------------------------------------- decimal places

def check_places(sid, selected, decimals):
    """Every figure (not a code) must have exactly `decimals` decimal places, as published, with one exception: the
    Commission prints a true zero as a plain 0 in a one-decimal table (for example SA and ACT in table 19A.11, "No
    service need identified"). A plain 0 is accepted and stored as published; the page shows it with the series' decimals."""
    check_decimals(sid, {y: {c: ("0.0" if t == "0" and decimals else t) for c, t in cells.items()} for y, cells in selected.items()}, decimals)


# ---------------------------------------------------------------- run

def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # ---- RoGS: find, download, read, cross-check
    log(f"Looking for the RoGS files on {rogs.FRONT_URL}")
    found = rogs.discover(fetcher, [CSV_SLUG, XLSX_SLUG], log=log)
    csv_url, xlsx_url = found.files[CSV_SLUG], found.files[XLSX_SLUG]
    log(f"RoGS edition {found.edition}" + (f" (the {found.fell_back_from} edition does not have the homelessness services section yet)" if found.fell_back_from else "") + f": {csv_url}")
    raw_csv = fetcher(csv_url, "*/*")
    raw_xlsx = fetcher(xlsx_url, "*/*")
    ds = rogs.parse_dataset(raw_csv)

    selected, checked, years_of_series = {}, {}, {}
    wb_cache = {}
    for sid, spec in SERIES.items():
        where = {"Table_Number": spec["table"], **spec["where"]}
        all_years = rogs.years_of(ds, where)
        if spec["kind"] == "census":
            table_years = all_years
            if not table_years:
                raise ScrapeError(f"{sid}: no rows match {where}")
            for y in table_years:
                census_date(y)  # refuses a Census with no known Census night
            check_census_years(table_years)
        else:
            table_years = [y for y in all_years if financial_year(y)[0] >= FIRST_YEAR]
            if not table_years:
                raise ScrapeError(f"{sid}: no rows match {where} from {FIRST_YEAR}")
            check_years(table_years)
        years_of_series[sid] = table_years
        selected[sid] = rogs.select(ds, where, table_years, label=f"the RoGS CSV, {sid}")
        check_places(sid, selected[sid], spec["decimals"])
        if spec["table"] not in wb_cache:
            wb_cache[spec["table"]] = rogs.read_workbook(raw_xlsx, spec["table"])
        checked[sid] = rogs.cross_check(selected[sid], wb_cache[spec["table"]], spec["workbook"], label=f"the RoGS workbook, {sid}")
        log(f"Cross-check {sid} (table {spec['table']}): {checked[sid]} figures ({len(table_years)} years x {len(rogs.JURISDICTIONS)} columns) agree between the CSV and the workbook.")
    for kind in ("census", "service"):
        same = {tuple(v) for sid, v in years_of_series.items() if SERIES[sid]["kind"] == kind}
        if len(same) != 1:
            raise ScrapeError(f"the {kind} series do not cover the same years: { {s: v for s, v in years_of_series.items() if SERIES[s]['kind'] == kind} }")
    census_years = years_of_series["census_homeless_rate"]
    service_years = years_of_series["clients"]
    total = sum(checked.values())
    log(f"RoGS section 19: {total} of {total} figures agree between the CSV and the workbook; Censuses {', '.join(census_years)}; financial years {service_years[0]} to {service_years[-1]}.")

    # ---- rows
    new_rows = []
    for sid, cells_by_year in selected.items():
        kind = SERIES[sid]["kind"]
        for y, cells in cells_by_year.items():
            for col, text in cells.items():
                new_rows.append({"date": date_of(kind, y), "period": y, "series": sid, "jurisdiction": JURISDICTION[col],
                                 "value": text, "unit": SERIES[sid]["unit"], "status": STATUS})

    # ---- history
    data_path = root / "metrics" / SLUG / "data.csv"
    manifest_path = root / "metrics" / SLUG / "sources" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    old_all = read_csv_rows(data_path)
    old_editions = (manifest.get(EDITIONS_KEY) or {}).get("editions", {})
    carried = set(census_years) | set(service_years)
    all_rows, editions = rogs.merge_history(old_all, new_rows, carried, found.edition, old_editions)
    kept = len(all_rows) - len(new_rows)
    if kept:
        log(f"Kept {kept} stored rows for periods the {found.edition} edition no longer carries (unchanged).")
    key_count = lambda rows: {k: sum(1 for r in rows if (r["series"], r["jurisdiction"]) == k) for k in {(r["series"], r["jurisdiction"]) for r in rows}}  # noqa: E731
    new_counts, old_counts = key_count(all_rows), key_count(old_all)
    for k, n in old_counts.items():
        if new_counts.get(k, 0) < n:
            raise ScrapeError(f"{k[0]} ({k[1]}) now has {new_counts.get(k, 0)} rows, fewer than the {n} already in data.csv. Rows must never fall.")

    # ---- report (for the checking notes)
    for sid in SERIES:
        ys = years_of_series[sid]
        log(f"{sid}, Australia: " + ", ".join(f"{y} {selected[sid][y]['Aust']}" for y in ys))
    log(f"census_homeless_rate, {census_years[-1]}: " + ", ".join(f"{JURISDICTION[c]} {selected['census_homeless_rate'][census_years[-1]][c]}" for c in rogs.JURISDICTIONS if JURISDICTION[c] != NATIONAL))
    log(f"clients, {service_years[-1]}: " + ", ".join(f"{JURISDICTION[c]} {selected['clients'][service_years[-1]][c]}" for c in rogs.JURISDICTIONS if JURISDICTION[c] != NATIONAL))
    codes = sorted({(sid, y, JURISDICTION[c], t) for sid, by in selected.items() for y, cells in by.items() for c, t in cells.items() if rogs.is_code(t)})
    log(f"Codes in the selected figures: {len(codes)}" + ("".join(f"\n  {sid} {y} {j}: {t}" for sid, y, j, t in codes) if codes else "."))

    # ---- nothing has failed: write everything
    retrieved = datetime.now(timezone.utc).date().isoformat()
    sources = root / "metrics" / SLUG / "sources"
    files = [(csv_url.split("?")[0].rsplit("/", 1)[-1], csv_url, raw_csv), (xlsx_url.split("?")[0].rsplit("/", 1)[-1], xlsx_url, raw_xlsx)]
    for name, url, raw in files:
        manifest[name] = {"url": url, "retrieved": retrieved, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        write_atomic(sources / name, raw)
    manifest[EDITIONS_KEY] = {"editions": editions}
    write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(data_path, build_csv(all_rows))
    log(f"Wrote metrics/{SLUG}/data.csv ({len(all_rows)} rows), saved the raw downloads and the manifest.")
    return {"census_years": census_years, "service_years": service_years, "selected": selected, "checked": checked, "codes": codes, "editions": editions, "rows": all_rows, "edition": found.edition}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download homelessness figures (Census and services) and write their data file.")
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
