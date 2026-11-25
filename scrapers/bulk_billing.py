#!/usr/bin/env python3
"""Bulk billing scraper: one stored series, one metric folder (metrics/bulk-billing/).

Financial years 2015-16 onwards, from the Productivity Commission's Report on Government Services (RoGS),
section 10 (primary and community health), read with scrapers/rogs.py from the Commission's CSV and checked
figure by figure against its Excel tables. The one series is picked by exact matches on named CSV columns (the
table number always among them):
  gp_bulk_billed_pct   table 10A.28, Measure "Non-referred attendances that were bulk billed", Age "All ages",
                       Sex "All people", Indigenous_Status "All people", Remoteness "All areas", Unit "%"
                       (one decimal place), the Australia column ("Aust") only: bulk billing is a Commonwealth
                       program and the page has no state panel.
Table 10A.27 is NOT used: it holds the same measure split by remoteness (and has only the Australia column), so
the same selection matches 10A.27 and 10A.28 for Australia; its "All ages, All areas" row has the same figure
today, but it is a different table. The table number is part of the selection, and a test proves the loader
refuses the selection when the table number is left out.

A year is written as the Commission writes it ("2024-25") in the period column, and dated 30 June of the second
year (2025-06-30). Figures are stored exactly as published (the number of decimal places is checked). Codes in
the Commission's tables (.., na, np, -) would be stored as codes; none are in this selection today.

History: each RoGS edition carries ten years. Rows already stored for years the new edition no longer carries are
kept unchanged; years in both come from the new edition (the checker's revision test then decides whether a
changed figure is accepted). sources/manifest.json records, in a "rogs-editions" entry, the edition each stored
year last came from.

Run from anywhere:  python3 scrapers/bulk_billing.py

If any check fails nothing is written and the exit code is 1.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import abs_series as abs_
import rogs
from abs_series import ScrapeError
from cpi_june import write_atomic
from hospital_waits import EDITIONS_KEY, JURISDICTION, STATUS, build_csv, check_decimals, check_years, financial_year, read_csv_rows

ROOT = Path(__file__).resolve().parents[1]
SLUG = "bulk-billing"

CSV_SLUG = "section10-primary-and-community-health-dataset"
XLSX_SLUG = "section10-primary-and-community-health-data-tables"
FIRST_YEAR = 2015  # the first year of the first financial year kept (2015-16)

# The CSV columns stored: Australia only.
COLUMNS = ["Aust"]

# One entry per stored series (the same shape as scrapers/hospital_waits.py). `where` are the exact CSV column
# matches (the CSV Unit among them); `workbook` says where the same figure is in the Excel table: the row label
# above it (footnote marks removed; the year is a row of its own above its figures).
SERIES = {
    "gp_bulk_billed_pct": {
        "table": "10A.28", "unit": "pct", "decimals": 1,
        "where": {"Measure": "Non-referred attendances that were bulk billed", "Age": "All ages", "Sex": "All people",
                  "Indigenous_Status": "All people", "Remoteness": "All areas", "Unit": "%"},
        "workbook": {"path": ("All ages",), "group": None},
    },
}


def run(root=ROOT, fetcher=abs_.fetch, log=print):
    root = Path(root)

    # ---- RoGS: find, download, read, cross-check
    log(f"Looking for the RoGS files on {rogs.FRONT_URL}")
    found = rogs.discover(fetcher, [CSV_SLUG, XLSX_SLUG], log=log)
    csv_url, xlsx_url = found.files[CSV_SLUG], found.files[XLSX_SLUG]
    log(f"RoGS edition {found.edition}" + (f" (the {found.fell_back_from} edition does not have the primary and community health section yet)" if found.fell_back_from else "") + f": {csv_url}")
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
        selected[sid] = rogs.select(ds, where, table_years, columns=COLUMNS, label=f"the RoGS CSV, {sid}")
        check_decimals(sid, selected[sid], spec["decimals"])
        wb = spec["workbook"]
        key = (spec["table"], wb["group"])
        if key not in wb_cache:
            wb_cache[key] = rogs.read_workbook(raw_xlsx, spec["table"], group=wb["group"])
        checked[sid] = rogs.cross_check(selected[sid], wb_cache[key], wb["path"], label=f"the RoGS workbook, {sid}", columns=COLUMNS)
        log(f"Cross-check {sid} (table {spec['table']}): {checked[sid]} figures ({len(table_years)} years x {len(COLUMNS)} column) agree between the CSV and the workbook.")
    years = years_of_series["gp_bulk_billed_pct"]
    total = sum(checked.values())
    log(f"RoGS section 10: {total} of {total} figures agree between the CSV and the workbook; years {years[0]} to {years[-1]}.")

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
    for sid in SERIES:
        log(f"{sid}, Australia: " + ", ".join(f"{y} {selected[sid][y]['Aust']}" for y in years))
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
    ap = argparse.ArgumentParser(description="Download the GP bulk billing rate and write its data file.")
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
