#!/usr/bin/env python3
"""One-off converter for the prototype debt data.

It turns the machine-read table in
metrics/commonwealth-debt/sources/fbo-2024-25-appendix-b-machine-read.csv
into metrics/commonwealth-debt/data.csv (the long format described in
metrics/README.md). It will be replaced by the real scraper in WP2.

Run from the repository root:  python3 scrapers/tools/make_debt_prototype_csv.py

Figures are copied as the source text, never retyped or reformatted.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "metrics/commonwealth-debt/sources/fbo-2024-25-appendix-b-machine-read.csv"
OUT = ROOT / "metrics/commonwealth-debt/data.csv"

# (series id, source column, unit)
SERIES = [
    ("gross_debt", "gross_debt_m", "aud_million"),
    ("net_debt", "net_debt_m", "aud_million"),
    ("gross_debt_pct_gdp", "gross_debt_pct_gdp", "pct_gdp"),
    ("net_debt_pct_gdp", "net_debt_pct_gdp", "pct_gdp"),
]


def period_end_date(period: str) -> str:
    """'2024-25' -> '2025-06-30' (30 June of the year the financial year ends)."""
    start = int(period[:4])
    end = start + 1
    if int(period[5:]) != end % 100:
        sys.exit(f"Unexpected period label: {period}")
    return f"{end}-06-30"


def main() -> None:
    with SRC.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for series, col, unit in SERIES:
        for r in rows:
            out.append([period_end_date(r["fy"]), r["fy"], series, "Commonwealth", r[col], unit, "actual"])
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "period", "series", "jurisdiction", "value", "unit", "status"])
        w.writerows(out)
    print(f"Wrote {len(out)} rows to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
