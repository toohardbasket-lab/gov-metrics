#!/usr/bin/env python3
"""One-off converter for the prototype price index.

It turns metrics/commonwealth-debt/sources/ato-cpi-june-quarter-2011-12-base.csv
(June quarter CPI, all groups, eight capitals, as shown by the ATO) into
shared/cpi_june.csv. It will be replaced by an ABS-based scraper in WP2.

Run from the repository root:  python3 scrapers/tools/make_cpi_june_csv.py
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "metrics/commonwealth-debt/sources/ato-cpi-june-quarter-2011-12-base.csv"
OUT = ROOT / "shared/cpi_june.csv"
BASE = "2011-12=100"


def main() -> None:
    with SRC.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "index", "base"])
        for r in rows:
            w.writerow([f"{int(r['june_year'])}-06-30", r["cpi"], BASE])
    print(f"Wrote {len(rows)} rows to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
