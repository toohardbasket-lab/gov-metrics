# Checking record: Bulk billing

## Status

One series on the page, stored. No figure is typed or edited by hand. The scraper is `scrapers/bulk_billing.py`, which uses the reusable Report on Government Services loader `scrapers/rogs.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `gp_bulk_billed_pct` | Productivity Commission, Report on Government Services (RoGS) 2026, section 10 Primary and community health, table 10A.28, Measure "Non-referred attendances that were bulk billed", Age "All ages", Sex "All people", Indigenous_Status "All people", Remoteness "All areas", Unit "%". One decimal, as published. Australia (the `Aust` column) only. | `sources/rogs-2026-parte-section10-primary-and-community-health-dataset_0.csv` |

**Australia only.** Table 10A.28 also has a figure for each state and territory, and the scraper does not store them: bulk billing is a Commonwealth program and plan section 3 gives it no state panel.

**Table 10A.27 is not used.** It holds the same measure split by remoteness and has only the Australia column. Its "All ages, All areas" row has the same figure as table 10A.28 in every year (checked, 24 November 2026 edition, all ten years), so the two tables are indistinguishable by value; the table number is part of the selection, and a test proves the loader refuses the selection when the table number is left out (two rows match for each year) and that a changed 10A.27 figure changes nothing stored.

Second source, used only as a check: the RoGS Excel tables (`sources/rogs-2026-parte-section10-primary-and-community-health-data-tables_0.xlsx`), sheet "Table 10A.28". The year is a row of its own above its figures, the age rows below it are labelled "All ages (g)" (footnote mark removed by the loader), and the sheet's age labels use an en dash ("0–15 years old"), which does not matter because only "All ages" is read.

**Dates.** A financial year is written as the Commission writes it in the `period` column ("2024-25") and dated 30 June of the second year (2025-06-30), as on the other Commission pages. The page's chart, tiles and table show the period label.

**Codes.** The Commission's codes would be stored as codes in `data.csv`, never as zero. None are in this selection.

**History.** Each RoGS edition carries ten years. When a later edition drops the earliest year, the scraper keeps the stored row for that year unchanged and takes the years in both from the new edition; the checker's revision test (0.3 points) then decides whether a changed past figure is accepted. `sources/manifest.json` holds a `rogs-editions` entry recording the edition each stored year last came from (all ten years are from the 2026 edition now).

**The "Latest official figure" row in metric.yml is typed by hand from the Department's snapshot and must be updated each quarter.** It is not in `data.csv` and is not checked by any code. The status block in `metric.yml` (Too early to say) is also set by hand: update it when the 2025-26 figure is published. Its `due` date is 2030-12-31 only because the checker needs a real date; the target says "by 2030" and does not say which day or whether a calendar or financial year.

The check required before publication (plan rule 8.8) is recorded below.

## What the scraper checked (run of 25 November 2026)

- RoGS edition found: 2026 (the newest year on the RoGS front page; its data-downloads page has the section 10 files). Files found by the slugs `section10-primary-and-community-health-dataset` and `section10-primary-and-community-health-data-tables`.
- Years 2015-16 to 2024-25 (10 years, consecutive), exactly one CSV row per year and selection.
- Number of decimal places checked: every figure has exactly one.
- **CSV against the Excel tables: 10 of 10 figures agree** (1 series x 10 years x 1 column).
- `data.csv`: 10 rows. Dates are 30 June of the second year; the period is the financial year; unit `pct`; status actual. Two runs in a row gave a byte-identical `data.csv`, manifest and raw files.
- A separate comparison written for this record (plain `csv` reading, selecting by the exact column values, not the loader): all 10 values in `data.csv` equal the raw CSV in `sources/`, no difference.

Australia, all ten years (per cent of non-referred GP attendances bulk billed):

| Financial year | Bulk billed % |
|---|---|
| 2015-16 | 85.1 |
| 2016-17 | 85.7 |
| 2017-18 | 86.1 |
| 2018-19 | 86.2 |
| 2019-20 | 87.5 |
| 2020-21 | 88.8 |
| 2021-22 | 88.3 |
| 2022-23 | 80.2 |
| 2023-24 | 77.3 |
| 2024-25 | 77.9 |

## Settings in `metric.yml` worth knowing

- Revision tolerance `{max_abs: 0.3}`: a change of more than 0.3 points to an accepted past year blocks until accepted with `npm run accept-revisions`.
- Plausible range 0 to 100.
- The chart has one view with a reference line at 90 (the target, solid) and its axis extended to 30 June 2030 (`to`). The line is the target, not a forecast.
- Target status "Too early to say", set by this site: no official body rates progress, and the yearly figures end before the expanded incentives began on 1 November 2025.
- No state panel (`state_panel: false`).

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: every figure in the page's table (all ten years) was compared with table 10A.28 in the Productivity Commission's section 10 CSV dataset, downloaded again for this check and read by separate code. The figures quoted by hand in Targets (84.1 per cent for April to June 2026; the start of the expanded incentives on 1 November 2025; the 9 in 10 by 2030 target) were checked against the Department of Health's published snapshot, media release and Budget 2025-26 fact sheet as found by web search on 25 November 2026.

Result: 10 figures compared, all matched.

| Point | Page |
|---|---|
| 2024-25 | 77.9 |
| 2023-24 | 77.3 |
| 2022-23 | 80.2 |
| 2021-22 | 88.3 |
| 2020-21 | 88.8 |
| 2019-20 | 87.5 |
| 2018-19 | 86.2 |
| 2017-18 | 86.1 |
| 2016-17 | 85.7 |
| 2015-16 | 85.1 |
