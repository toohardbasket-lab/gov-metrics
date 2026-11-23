# Scrapers

Scrapers are written in Python. Each one downloads an official source file, saves the raw file unchanged, and writes a versioned CSV. They need Python 3 and the packages in `requirements.txt` (install with `pip install -r scrapers/requirements.txt`). Run them from the project folder.

| Script | What it does |
|---|---|
| `commonwealth_debt.py [year]` | Downloads Appendix B and Part 1 of the Final Budget Outcome (Word files) from archive.budget.gov.au, reads Tables B.4 (net debt) and B.5 (total AGS on issue) in code, and writes `metrics/commonwealth-debt/data.csv`. The year is the folder name in the web address and defaults to `2025-26`. Raw files and `sources/manifest.json` go in `metrics/commonwealth-debt/sources/`. |
| `cpi_june.py` | Downloads the quarterly Consumer Price Index from the ABS Data API, keeps the June quarters from 1971, and writes `shared/cpi_june.csv`. The raw response and `shared/sources/manifest.json` go in `shared/sources/`. |
| `unemployment_rate.py` | Downloads the monthly unemployment rate (series `M13.3.1599.20.AUS.M`) from the ABS Data API, rounds each value to the ABS's own number of decimal places (half up), finds the current Labour Force Table 1 spreadsheet link on the ABS "latest release" page, and refuses to write unless spreadsheet series A84423050A agrees for every month and ends on the same month. Writes `metrics/unemployment-rate/data.csv`; the raw API response and spreadsheet and `sources/manifest.json` go in `metrics/unemployment-rate/sources/`. The reading and checking helpers are in `abs_series.py`, which any later ABS series can reuse. |
| `run_all.py --status <file>` | Runs every scraper in turn (the list is at the top of the file), carries on if one fails, and writes a small JSON file saying how each went, with the last 30 lines it printed. It exits 0 even when a scraper failed, because the report carries the failure. |
| `report.py --before <folder> --after <folder> --status <file> --out <file.md>` | Compares the `metrics/` and `shared/` folders of two copies of the project and writes the weekly "what changed" report (see below). Optional: `--changed-flag <file>` writes true or false, `--today YYYY-MM-DD` is for testing. It does not use git. |

The download scrapers check everything first and write nothing if a check fails. They print `ERROR:` and exit with code 1. The debt scraper stops if a table is not found, a year is missing or repeated, a value cannot be read (it understands every kind of minus sign and ignores footnote markers), the two tables cover different years, a value is outside a sensible range, the row count falls, or the latest year does not match the Part 1 overview table. The price scraper stops if a June quarter is missing. The unemployment scraper stops on a non-200 answer, a missing column, any unexpected dimension code, a repeated or missing month, an unreadable value, the spreadsheet disagreeing with the API about any month or about the latest month, or fewer rows than before.

The manifest records, for each saved file, the web address, the date retrieved (UTC), a SHA-256 checksum and the size in bytes.

## The weekly update and its report

`.github/workflows/weekly-update.yml` copies `metrics/` and `shared/` aside, runs `run_all.py`, then runs `report.py` to compare the before and after copies. The report has these sections, each saying "None" when empty: new data points, revised history (old and new value and the difference), removed data points (this should never happen and is flagged loudly), sources (whether each downloaded file changed, and any scraper that failed with what it printed), shared files (the price index; a change to it changes every inflation-adjusted figure), targets due within 90 days, and what to do.

Each revised figure that is over its series' allowed revision (the `revision` setting in `metric.yml`, see `metrics/README.md`) starts with **LARGE:**. `report.py` reads that setting with its own small YAML reader, which understands only the one-line form `revision: {max_abs: 500, max_pct: 1, pct_floor: 5000}` under each series. If a series' setting is written any other way, the report says it could not read it and marks nothing for that series; the validator still enforces it. The rule used is the same as the validator's (`scripts/validate.mjs`).

If anything changed, the job runs `npm run validate`, then `npm run accept-data` and `npm run build`, and opens a pull request on a branch named `data-update/<date>` with the report as its description. The owner reads the report, checks the figures against the source, and merges, or closes the pull request. If validation fails, nothing is committed and an issue called "Weekly update blocked: validation failed" is opened or updated; when the cause is a large revision to a past figure, the issue says so. The owner then accepts a genuine revision on the PC with `npm run accept-data -- --accept-revisions`, and commits and pushes the result. If nothing changed but a source could not be read, an issue called "Weekly update: a source could not be read" is opened or updated. If nothing changed and nothing failed, the job finishes quietly. Nothing is pushed to the main branch directly.

The job's download dates (the "retrieved" lines in the manifests) change every week even when the figures do not. The report ignores them when deciding whether anything changed, so an ordinary quiet week makes no pull request.

One setting is needed once, on GitHub: Settings, Actions, General, Workflow permissions, and tick "Allow GitHub Actions to create and approve pull requests".

Tests: `python3 scrapers/tests/test_report.py` (the report and `run_all.py`, no network), `python3 scrapers/tests/test_commonwealth_debt.py` and `python3 scrapers/tests/test_unemployment_rate.py`.

The debt scraper's tests run without a network. They read a saved copy of the 2024-25 Appendix B file and compare it with the figures a language model once read from the PDF (both in `scrapers/tests/fixtures/`).

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
