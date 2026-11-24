#!/usr/bin/env python3
"""Hospital waits scraper: four stored series, one metric folder (metrics/hospital-waits/).

Financial years 2015-16 onwards, from the Productivity Commission's Report on Government Services (RoGS),
section 12 (public hospitals), read with scrapers/rogs.py from the Commission's CSV and checked figure by
figure against its Excel tables. Each series is picked by exact matches on named CSV columns (a table number
always among them):
  ed_seen_on_time        table 12A.13, Measure "Emergency department waiting times", Hospital_Sector_Grp
                         "All public hospitals", Description3 "Patients seen on time", Triage_Category
                         "Total excluding unknown triage category", Unit "%" (whole numbers)
  ed_within_4_hours      table 12A.18, Measure "Patients staying for four hours or less", Description3
                         "ED stay length is within four hours", Unit "%" (one decimal)
  surgery_median_days    table 12A.23, Measure "Elective surgery: waiting times", Hospital_Sector_Grp
                         "All public hospitals", Description3 "50th percentile", Description5 "Total", Unit "days"
  surgery_90th_days      the same with Description3 "90th percentile"
Table 12A.24 is NOT used: it holds two rows per year for the same labels (all patients, and a subgroup) with
different coverage. Table 12A.23 is the all-patients table, and the table number is part of every selection.

A year is written as the Commission writes it ("2024-25") in the period column, and dated 30 June of the second
year (2025-06-30). Figures are stored exactly as published (the number of decimal places is checked: 12A.13 has
none, 12A.18 has one). Codes in the Commission's tables (.., na, np, -) are stored as codes; the metric decides
what they mean.

History: each RoGS edition carries ten years. Rows already stored for years the new edition no longer carries are
kept unchanged; years in both come from the new edition (the checker's revision test then decides whether a
changed figure is accepted). sources/manifest.json records, in a "rogs-editions" entry, the edition each stored
year last came from.

Run from anywhere:  python3 scrapers/hospital_waits.py

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
from pathlib import Path

import abs_series as abs_
import rogs
from abs_series import ScrapeError
from cpi_june import write_atomic

ROOT = Path(__file__).resolve().parents[1]
SLUG = "hospital-waits"

CSV_SLUG = "section12-public-hospitals-dataset"
XLSX_SLUG = "section12-public-hospitals-data-tables"
FIRST_YEAR = 2015  # the first year of the first financial year kept (2015-16)
EDITIONS_KEY = "rogs-editions"

# The jurisdiction names written to data.csv: the same scheme as metrics/rents and metrics/social-housing.
JURISDICTION = {"NSW": "New South Wales", "Vic": "Victoria", "Qld": "Queensland", "WA": "Western Australia", "SA": "South Australia",
                "Tas": "Tasmania", "ACT": "Australian Capital Territory", "NT": "Northern Territory", "Aust": "Australia"}
NATIONAL = "Australia"
STATES = ["New South Wales", "Victoria", "Queensland", "Western Australia", "South Australia", "Tasmania",
          "Australian Capital Territory", "Northern Territory"]

# One entry per stored series. `where` are the exact CSV column matches (the CSV Unit among them: "%" or "days").
# `unit` is the unit written to data.csv. `workbook` says where the same figure is
# in the Excel table: the row labels above it (footnote marks removed), the Unit, and, for a sheet with two sets of
# columns, the heading of the set. `decimals` is the number of decimal places the Commission prints; every figure
# (not a code) must have exactly that many.
SERIES = {
    "ed_seen_on_time": {
        "table": "12A.13", "unit": "pct", "decimals": 0,
        "where": {"Measure": "Emergency department waiting times", "Hospital_Sector_Grp": "All public hospitals",
                  "Description3": "Patients seen on time", "Triage_Category": "Total excluding unknown triage category", "Unit": "%"},
        "workbook": {"path": ("All public hospitals", "Emergency department", "Patients seen on time", "Total", "%"), "group": None},
    },
    "ed_within_4_hours": {
        "table": "12A.18", "unit": "pct", "decimals": 1,
        "where": {"Measure": "Patients staying for four hours or less", "Description3": "ED stay length is within four hours", "Unit": "%"},
        "workbook": {"path": ("Emergency department", "Presentations", "ED stay length is within four hours", "%"), "group": None},
    },
    "surgery_median_days": {
        "table": "12A.23", "unit": "days", "decimals": 0,
        "where": {"Measure": "Elective surgery: waiting times", "Hospital_Sector_Grp": "All public hospitals",
                  "Description3": "50th percentile", "Description5": "Total", "Unit": "days"},
        "workbook": {"path": ("All public hospitals", "Total", "days"), "group": "50th percentile"},
    },
    "surgery_90th_days": {
        "table": "12A.23", "unit": "days", "decimals": 0,
        "where": {"Measure": "Elective surgery: waiting times", "Hospital_Sector_Grp": "All public hospitals",
                  "Description3": "90th percentile", "Description5": "Total", "Unit": "days"},
        "workbook": {"path": ("All public hospitals", "Total", "days"), "group": "90th percentile"},
    },
}

HEADER = "date,period,series,jurisdiction,value,unit,status"
STATUS = "actual"
LABEL_RE = re.compile(r"(\d{4})-(\d{2})")


# ---------------------------------------------------------------- years

def financial_year(label):
    """'2024-25' -> (2024, '2025-06-30'): the first year, and 30 June of the second. Refuses a label whose
    second part is not the year after the first."""
    m = LABEL_RE.fullmatch(label)
    if not m:
        raise ScrapeError(f"the year {label!r} is not a financial year such as 2024-25")
    first, second = int(m.group(1)), int(m.group(2))
    if (first + 1) % 100 != second:
        raise ScrapeError(f"the year {label!r} is not two consecutive years")
    return first, f"{first + 1}-06-30"


def check_years(years):
    """The years must run without a gap from one to the next."""
    firsts = [financial_year(y)[0] for y in years]
    if firsts != list(range(firsts[0], firsts[0] + len(firsts))):
        raise ScrapeError(f"the financial years {years} are not consecutive")


def check_decimals(sid, selected, decimals):
    """Every figure (not a code) must have exactly `decimals` decimal places, as published."""
    for year, cells in selected.items():
        for col, text in cells.items():
            if rogs.is_code(text):
                continue
            places = len(text.split(".")[1]) if "." in text else 0
            if places != decimals:
                raise ScrapeError(f"{sid}: {year} {col} is {text!r}; the Commission prints {decimals} decimal place(s) for this series, so the figure is not as expected")


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


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # ---- RoGS: find, download, read, cross-check
    log(f"Looking for the RoGS files on {rogs.FRONT_URL}")
    found = rogs.discover(fetcher, [CSV_SLUG, XLSX_SLUG], log=log)
    csv_url, xlsx_url = found.files[CSV_SLUG], found.files[XLSX_SLUG]
    log(f"RoGS edition {found.edition}" + (f" (the {found.fell_back_from} edition does not have the public hospitals section yet)" if found.fell_back_from else "") + f": {csv_url}")
    raw_csv = fetcher(csv_url, "*/*")
    raw_xlsx = fetcher(xlsx_url, "*/*")
    ds = rogs.parse_dataset(raw_csv)

    selected, checked, years_of_series = {}, {}, {}
    wb_cache = {}
    for sid, spec in SERIES.items():
        where = {"Table_Number": spec["table"], **spec["where"]}
        table_years = [y for y in rogs.years_of(ds, where) if financial_year(y)[0] >= FIRST_YEAR]
        if not table_years:
            raise ScrapeError(f"{sid}: no rows match {where} from {FIRST_YEAR}")
        check_years(table_years)
        years_of_series[sid] = table_years
        selected[sid] = rogs.select(ds, where, table_years, label=f"the RoGS CSV, {sid}")
        check_decimals(sid, selected[sid], spec["decimals"])
        wb = spec["workbook"]
        key = (spec["table"], wb["group"])
        if key not in wb_cache:
            wb_cache[key] = rogs.read_workbook(raw_xlsx, spec["table"], group=wb["group"], unit_in_path=True)
        checked[sid] = rogs.cross_check(selected[sid], wb_cache[key], wb["path"], label=f"the RoGS workbook, {sid}")
        log(f"Cross-check {sid} (table {spec['table']}): {checked[sid]} figures ({len(table_years)} years x {len(rogs.JURISDICTIONS)} columns) agree between the CSV and the workbook.")
    if len({tuple(v) for v in years_of_series.values()}) != 1:
        raise ScrapeError(f"the four series do not cover the same years: {years_of_series}")
    years = years_of_series["ed_seen_on_time"]
    total = sum(checked.values())
    log(f"RoGS section 12: {total} of {total} figures agree between the CSV and the workbook; years {years[0]} to {years[-1]}.")

    # ---- rows
    new_rows = []
    for sid, cells_by_year in selected.items():
        for y, cells in cells_by_year.items():
            for col, text in cells.items():
                new_rows.append({"date": financial_year(y)[1], "period": y, "series": sid, "jurisdiction": JURISDICTION[col],
                                 "value": text, "unit": SERIES[sid]["unit"], "status": STATUS})

    # ---- history
    data_path = root / "metrics" / SLUG / "data.csv"
    manifest_path = root / "metrics" / SLUG / "sources" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    old_all = read_csv_rows(data_path)
    old_editions = (manifest.get(EDITIONS_KEY) or {}).get("editions", {})
    all_rows, editions = rogs.merge_history(old_all, new_rows, set(years), found.edition, old_editions)
    kept = len(all_rows) - len(new_rows)
    if kept:
        log(f"Kept {kept} stored rows for years the {found.edition} edition no longer carries (unchanged).")
    key_count = lambda rows: {k: sum(1 for r in rows if (r["series"], r["jurisdiction"]) == k) for k in {(r["series"], r["jurisdiction"]) for r in rows}}  # noqa: E731
    new_counts, old_counts = key_count(all_rows), key_count(old_all)
    for k, n in old_counts.items():
        if new_counts.get(k, 0) < n:
            raise ScrapeError(f"{k[0]} ({k[1]}) now has {new_counts.get(k, 0)} rows, fewer than the {n} already in data.csv. Rows must never fall.")

    # ---- report (for the checking notes)
    latest = max(years)
    for sid in SERIES:
        log(f"{sid}, Australia: " + ", ".join(f"{y} {selected[sid][y]['Aust']}" for y in years))
    for sid in ("ed_seen_on_time", "surgery_median_days"):
        log(f"{sid}, {latest}: " + ", ".join(f"{JURISDICTION[c]} {selected[sid][latest][c]}" for c in rogs.JURISDICTIONS if JURISDICTION[c] != NATIONAL))
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
    return {"years": years, "selected": selected, "checked": checked, "codes": codes, "editions": editions, "rows": all_rows, "edition": found.edition}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download public hospital waiting-time figures and write their data file.")
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
