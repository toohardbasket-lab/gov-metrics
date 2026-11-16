# Scrapers

Scrapers are written in Python. Each one downloads an official source file, saves the raw file unchanged, and writes a versioned CSV. They need Python 3 and the two packages in `requirements.txt` (install with `pip install -r scrapers/requirements.txt`). Run them from the project folder.

| Script | What it does |
|---|---|
| `commonwealth_debt.py [year]` | Downloads Appendix B and Part 1 of the Final Budget Outcome (Word files) from archive.budget.gov.au, reads Tables B.4 (net debt) and B.5 (total AGS on issue) in code, and writes `metrics/commonwealth-debt/data.csv`. The year is the folder name in the web address and defaults to `2025-26`. Raw files and `sources/manifest.json` go in `metrics/commonwealth-debt/sources/`. |
| `cpi_june.py` | Downloads the quarterly Consumer Price Index from the ABS Data API, keeps the June quarters from 1971, and writes `shared/cpi_june.csv`. The raw response and `shared/sources/manifest.json` go in `shared/sources/`. |

Both scrapers check everything first and write nothing if a check fails. They print `ERROR:` and exit with code 1. The debt scraper stops if a table is not found, a year is missing or repeated, a value cannot be read (it understands every kind of minus sign and ignores footnote markers), the two tables cover different years, a value is outside a sensible range, the row count falls, or the latest year does not match the Part 1 overview table. The price scraper stops if a June quarter is missing.

The manifest records, for each saved file, the web address, the date retrieved (UTC), a SHA-256 checksum and the size in bytes.

Tests: `python3 scrapers/tests/test_commonwealth_debt.py`. They run without a network. They read a saved copy of the 2024-25 Appendix B file and compare it with the figures a language model once read from the PDF (both in `scrapers/tests/fixtures/`).

Every scraper must follow the nine data rules from the build plan, in plain words:

1. Never type a figure. Every number comes from a file the scraper downloaded. The metric's definition file records the web address, the table, the date retrieved and a checksum of the file.
2. One folder per metric, holding `metric.yml`, `data.csv`, `sources/` (raw files as downloaded) and `NOTES.md`.
3. Use the long CSV shape (`date, period, series, jurisdiction, value, unit, status`). Status is `actual`, `estimate` or `forecast`. Dates are real dates, and the source's own period label goes in `period`.
4. Check the data before publishing, and refuse to publish if a check fails: no missing years inside a series; values inside a stated sensible range; the latest value matches a second official statement of the same figure where one exists; and the row count never falls between runs.
5. Work out derived figures (inflation-adjusted dollars, per person, straight-line pace) in code, label them as derived, and print the formula on the page.
6. Keep revisions. When a source revises its history, the old CSV stays in version history and the page notes that figures were revised and when.
7. Disclose conflicts. If two official sources disagree, show both and say so.
8. A person checks every new page before it is first published. They check the latest value and five other points against the source, and initial the metric's `NOTES.md`. A page without that check stays in draft.
9. A reading model is not a parser. Read the source file in code (the Excel or CSV version where one exists), then have a person spot-check it. Reading a PDF with a language model is only good enough for a prototype.
