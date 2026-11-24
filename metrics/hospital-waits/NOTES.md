# Checking record: Hospital waits

## Status

Four series on the page, all stored. No figure is typed or edited by hand. The scraper is `scrapers/hospital_waits.py`, which uses the reusable Report on Government Services loader `scrapers/rogs.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `ed_seen_on_time` | Productivity Commission, Report on Government Services (RoGS) 2026, section 12 Public hospitals, table 12A.13, Measure "Emergency department waiting times", Hospital_Sector_Grp "All public hospitals", Description3 "Patients seen on time", Triage_Category "Total excluding unknown triage category", Unit "%". Whole numbers, as published. | `sources/rogs-2026-parte-section12-public-hospitals-dataset_0.csv` |
| `ed_within_4_hours` | Same dataset, table 12A.18, Measure "Patients staying for four hours or less", Description3 "ED stay length is within four hours", Unit "%". One decimal, as published. (The same table has a count row with Unit "no." and the same Description3; the unit tells them apart.) | same file |
| `surgery_median_days` | Same dataset, table 12A.23, Measure "Elective surgery: waiting times", Hospital_Sector_Grp "All public hospitals", Description3 "50th percentile", Description5 "Total", Unit "days". | same file |
| `surgery_90th_days` | Same, Description3 "90th percentile". | same file |

**Table 12A.24 is not used.** It holds two rows per year for the same labels with different coverage (all patients, and a subgroup), so the same selection matches 12A.23 and two rows of 12A.24 (for Australia 2024-25: 12A.23 gives 45, 12A.24 gives 59 and 45). The table number is part of every selection, and a test proves the loader refuses the selection when the table number is left out.

Second source, used only as a check: the RoGS Excel tables (`sources/rogs-2026-parte-section12-public-hospitals-data-tables_0.xlsx`), sheets "Table 12A.13", "Table 12A.18" and "Table 12A.23". The layout differs from the housing workbook and from the CSV: the year is a row of its own above its figures; footnote marks are on labels and column headings ("WA (c)", "Total (f)"); 12A.18 has a count row and a per cent row with the same label (told apart by Unit); 12A.23 has two sets of jurisdiction columns side by side, headed "50th percentile" and "90th percentile". The sheets declare their size as the single cell A1, which makes the default reader see one cell; `rogs.read_workbook` resets the size and reads what is there. The loader finds each sheet by its name, each row by its labels and unit, and each column set by its heading.

**Dates.** A financial year is written as the Commission writes it in the `period` column ("2024-25") and dated 30 June of the second year (2025-06-30), as the debt page does. The page's chart, tiles and table show the period label; the chart's axis runs in calendar years, so the 2024-25 point sits at 30 June 2025.

**Codes.** The Commission's codes are stored as codes in `data.csv`, never as zero. The page draws no point for a code and the table shows the code. A figure that turns into a code, or a code into a figure, is always a revision the checker blocks until it is accepted. Found in this edition: six `na` (not available), four for the Australian Capital Territory in 2015-16 (one in each series) and two for the Northern Territory in 2023-24 (the two surgery series):

- `ed_seen_on_time`, Australian Capital Territory, 2015-16: na
- `ed_within_4_hours`, Australian Capital Territory, 2015-16: na
- `surgery_median_days`, Australian Capital Territory, 2015-16: na
- `surgery_90th_days`, Australian Capital Territory, 2015-16: na
- `surgery_median_days`, Northern Territory, 2023-24: na
- `surgery_90th_days`, Northern Territory, 2023-24: na

No `..`, `np` or `-` in the selected figures. So the ACT chart in the state panel starts in 2016-17.

**History.** Each RoGS edition carries ten years. When a later edition drops the earliest year, the scraper keeps the stored rows for that year unchanged and takes the years in both from the new edition; the checker's revision test (1 percentage point, 2 days) then decides whether a changed past figure is accepted. `sources/manifest.json` holds a `rogs-editions` entry that records, for each stored year, the edition it last came from (all ten years are from the 2026 edition now).

The page is a draft until the human check below is done.

## What the scraper checked (run of 24 November 2026)

- RoGS edition found: 2026 (the newest year on the RoGS front page; its data-downloads page has the section 12 files, so no fall back to 2025 was needed). Files found by the slugs `section12-public-hospitals-dataset` and `section12-public-hospitals-data-tables`. (The shorter slug `section12-public-hospitals` matches both the CSV and the Excel file on the page, so the loader refuses it; the two longer slugs each match one link.)
- Years 2015-16 to 2024-25 (10 years, consecutive, the same in all four series), nine columns (NSW, Vic, Qld, WA, SA, Tas, ACT, NT, Aust), exactly one CSV row per year and selection for each series.
- Number of decimal places checked: every figure of `ed_seen_on_time` and of `surgery_*` has none, every figure of `ed_within_4_hours` has exactly one ("52.0" stays "52.0"). The scraper refuses a figure with any other number of places.
- **CSV against the Excel tables: 360 of 360 figures agree** (4 series x 10 years x 9 columns; 90 each), including every code.
- `data.csv`: 360 rows (4 series x 9 jurisdictions x 10 years), sorted by series, jurisdiction, then date. Dates are 30 June of the second year; the period is the financial year; unit `pct` for the two emergency series and `days` for the two surgery series; status actual. Two runs in a row gave a byte-identical `data.csv`, manifest and raw files.
- A separate comparison written for this record (plain `csv` reading, selecting by the exact column values in the brief, not the loader): all 360 values and all 360 dates in `data.csv` equal the raw CSV in `sources/`, no difference.

Australia, all ten years:

| Financial year | Seen on time % | Stay of 4 hours or less % | Median wait (days) | 90th percentile (days) |
|---|---|---|---|---|
| 2015-16 | 74 | 73.2 | 38 | 263 |
| 2016-17 | 73 | 72.3 | 39 | 261 |
| 2017-18 | 72 | 71.1 | 41 | 270 |
| 2018-19 | 71 | 69.6 | 41 | 279 |
| 2019-20 | 74 | 69.2 | 39 | 281 |
| 2020-21 | 71 | 67.0 | 48 | 348 |
| 2021-22 | 67 | 60.9 | 40 | 323 |
| 2022-23 | 65 | 55.8 | 49 | 361 |
| 2023-24 | 67 | 55.0 | 46 | 329 |
| 2024-25 | 67 | 53.4 | 45 | 329 |

States and territories, 2024-25, in the page's fixed order:

| State or territory | Seen on time % | Median wait (days) |
|---|---|---|
| New South Wales | 73 | 69 |
| Victoria | 72 | 28 |
| Queensland | 72 | 42 |
| Western Australia | 46 | 45 |
| South Australia | 53 | 52 |
| Tasmania | 46 | 49 |
| Australian Capital Territory | 62 | 54 |
| Northern Territory | 48 | 41 |

## Settings in `metric.yml` worth knowing

- Revision tolerances: percentages `{max_abs: 1}` (a change of more than 1 percentage point blocks), days `{max_abs: 2}` (more than 2 days blocks). Tested: a 2-point change to a past Australian seen-on-time figure blocks; 1 point passes with a warning; 3 days blocks, 2 days passes.
- Plausible ranges: percentages 0 to 100, days 0 to 1,000 (the real range of the surgery figures is 25 to 588 days, the highest being Tasmania's 90th percentile in 2020-21).
- `decimals`: 0 for `ed_seen_on_time`, 1 for `ed_within_4_hours`: a display setting so the page shows the figure as published (67%, not 67.0%; 53.4%).
- The state panel charts `ed_seen_on_time` on a fixed scale of 0 to 100 (`y_range`); the extra column beside the figure is the surgery median wait for the same year, placed after the figure (`after: true`). The Australian Capital Territory chart starts in 2016-17 because 2015-16 is `na`.
- Chart lines: emergency view colours 1 and 2 (blue, orange), surgery view colours 3 and 4 (plum, green), so each series keeps its colour.
- The lede and chart description use `{first_period}` (added by the lead model on 24 November 2026), so they read "since 2015-16" and "2015-16 to 2024-25".

## Human check (plan rule 8.8)

Checked by:

Date:

Against:

Points checked:
