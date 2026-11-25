# Checking record: Homelessness

## Status

Seven series stored, one worked out (not stored). No figure is typed or edited by hand. The scraper is `scrapers/homelessness.py`, which uses the reusable Report on Government Services loader `scrapers/rogs.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `census_homeless_rate` | Productivity Commission, Report on Government Services (RoGS) 2026, section 19 Homelessness services, table 19A.2, Measure "Homelessness; by homelessness operational group", Description1 "People who are homeless by operational group", Description3 "Rate per 10000 people in the population", Description4 "Total", Unit "rate". One decimal. Years 2011, 2016, 2021. | `sources/rogs-2026-partg-section19-homelessness-services-dataset.csv` |
| `census_homeless_number` | Same table, Description3 "Number", Unit "no.". Whole numbers. | same file |
| `clients` | Table 19A.10, Measure "Unmet need", Description1 "Total clients", Unit "no.". Financial years 2020-21 to 2024-25. | same file |
| `unmet_accommodation_pct` | Table 19A.10, Description1 "Accommodation services", Description3 "Proportion of clients with unmet need", Unit "%". One decimal. | same file |
| `unassisted_accommodation_daily`, `unassisted_other_daily`, `unassisted_no_need_daily` | Table 19A.11, Measure "Unassisted requests", Description3 "Average daily unassisted requests", Description1 "Accommodation services", "Services other than accommodation", "No service need identified", Unit "no." (stored with the site's unit `per_day`). One decimal. | same file |
| `unassisted_daily_total` | Not stored. Worked out by the site as the sum of the three above (same code in the checker and the page, `src/lib/derive.mjs`). | none |

Every selection also names the table number and the Unit, so no other table or row can match. The scraper refuses unless there is exactly one CSV row per year for each selection.

Second source, used only as a check: the RoGS Excel tables (`sources/rogs-2026-partg-section19-homelessness-services-data-tables.xlsx`), sheets "Table 19A.2", "Table 19A.10" and "Table 19A.11". In the workbook the year is a row of its own (above the figures in 19A.2 and 19A.10; below a heading row in 19A.11), and footnote marks are on labels and column headings. The loader finds each sheet by its name and each row by its labels.

**Dates.** A Census is dated its Census night, from the map `CENSUS_NIGHT` in the scraper: 9 August 2011, 9 August 2016, 10 August 2021 (the period is the year). A Census year that is not in the map is refused, so a 2026 Census in a later edition stops the update until someone adds its date. A financial year is dated 30 June of its second year, with the Commission's label ("2024-25") as the period. The checker's new `census` frequency accepts dates five years apart give or take seven days, and refuses a missing Census.

**Codes.** None in the selected figures of this edition. A code would be stored as a code, and a figure that turned into a code, or a code into a figure, would be a revision the checker blocks until it is accepted.

**A plain zero.** The Commission prints a true zero as a plain `0` in the one-decimal table 19A.11 (South Australia and the Australian Capital Territory, "No service need identified", in several years; in the workbook it is the number 0). The scraper accepts a plain `0` in a one-decimal series and stores it as published; the page shows it as 0.0 a day. Any other figure with the wrong number of decimal places is refused.

**History.** Each RoGS edition carries only some years (three Censuses and five financial years in the 2026 edition). When a later edition drops a year, the scraper keeps the stored rows for it unchanged and takes the years in both from the new edition; the checker's revision test then decides whether a changed past figure is accepted. `sources/manifest.json` holds a `rogs-editions` entry recording the edition each stored period last came from (all from the 2026 edition now).

The check required before publication (plan rule 8.8) is recorded below; it was done by Claude at Alan's request, not by a person.

## What the scraper checked (run of 24 November 2026)

- RoGS edition found: 2026 (the newest year on the RoGS front page; its data-downloads page has the section 19 files). Files found by the slugs `section19-homelessness-services-dataset` and `section19-homelessness-services-data-tables`.
- Censuses 2011, 2016, 2021; financial years 2020-21 to 2024-25 (consecutive, the same in all five service series); nine columns (NSW, Vic, Qld, WA, SA, Tas, ACT, NT, Aust).
- **CSV against the Excel tables: 279 of 279 figures agree** (two Census series x 3 x 9 = 54, five service series x 5 x 9 = 225).
- `data.csv`: 279 rows, sorted by series, jurisdiction, then date. Units `rate`, `count`, `pct` and `per_day`; status actual. Two runs in a row gave a byte-identical `data.csv`, manifest and raw files.
- A separate comparison written for this record (plain `csv` reading with `python3 -I`, selecting by the exact column values in the brief, not the loader): all 279 values equal the raw CSV in `sources/`, no difference.

Australia:

| Census | Homeless (number) | Per 10,000 |
|---|---|---|
| 2011 | 102,439 | 47.6 |
| 2016 | 116,427 | 49.8 |
| 2021 | 122,494 | 48.2 |

| Financial year | Clients | Needed accommodation, not provided % | Accommodation a day | Other a day | No need a day | Total a day (worked out) |
|---|---|---|---|---|---|---|
| 2024-25 | 288,970 | 33.2 | 232.0 | 79.4 | 41.7 | 353.1 |
| 2023-24 | 280,078 | 32.8 | 208.6 | 62.9 | 28.5 | 300.0 |
| 2022-23 | 273,648 | 34.9 | 213.6 | 58.2 | 22.7 | 294.5 |
| 2021-22 | 272,694 | 33.9 | 203.2 | 59.9 | 24.8 | 287.9 |
| 2020-21 | 278,275 | 32.3 | 226.3 | 60.4 | 25.7 | 312.4 |

States and territories, in the page's fixed order:

| State or territory | Census 2021 per 10,000 | Clients 2024-25 | Needed accommodation, not provided % 2024-25 |
|---|---|---|---|
| New South Wales | 43.4 | 67,824 | 46.6 |
| Victoria | 47.1 | 105,126 | 34.2 |
| Queensland | 43.5 | 54,700 | 30.1 |
| Western Australia | 36.6 | 25,912 | 11.9 |
| South Australia | 41.7 | 17,587 | 25.6 |
| Tasmania | 42.1 | 6,323 | 27.8 |
| Australian Capital Territory | 39.1 | 4,194 | 23.2 |
| Northern Territory | 563.6 | 10,483 | 10.2 |

## Settings in `metric.yml` worth knowing

- Revision tolerances: Census rate `{max_abs: 0.1}`, Census count `{max_abs: 1}` (Census counts are final), clients `{max_abs: 1, max_pct: 1, pct_floor: 100}`, per cent `{max_abs: 0.5}`, per day `{max_abs: 1}`. Tested: a 0.5 change to the 2016 Australian Census rate blocks; 0.1 passes with a warning.
- Plausible ranges: Census counts 0 to 1,000,000, clients 0 to 2,000,000, per cent 0 to 100, per day 0 to 5,000. **Census rate 0 to 1,000, not the 0 to 500 in the brief:** the Northern Territory's real figures are 723.7 (2011), 599.6 (2016) and 563.6 (2021), so 0 to 500 fails the checker. Owner to confirm or change.
- The state panel charts `census_homeless_rate` on a fixed scale of 0 to 800: the highest state figure in the data (Northern Territory, 2011: 723.7) rounded up to the next 100. The checker refuses any figure outside it. The two columns after the rate show each place's own latest service figures (`own_latest`), the clients with their period.
- The three service views start their axis in 2020 (`from: 2020`) so their five points are not squeezed to the right of an axis that starts at the first Census.
- The page has two tables (a list under `table`): the Census table and the financial-year table. Each has a row for every date on which one of its own columns has a figure.

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page (the table at the foot of the page) were compared with official files downloaded again for this check, read by separate code written for the check, not the scraper's code. All three Censuses and all five financial years were checked, Australia figures. Worked-out figures were recalculated from the official figures. A planted error in a page cell was caught by the same check.

Against: Productivity Commission RoGS 2026 section 19 dataset, tables 19A.2, 19A.10 and 19A.11

Result: 36 figures compared, all matched.

| Point | Page |
|---|---|
| 2021 Census number | 122494 |
| 2021 Census rate | 48.2 |
| 2016 Census number | 116427 |
| 2016 Census rate | 49.8 |
| 2011 Census number | 102439 |
| 2011 Census rate | 47.6 |
| 2024-25 clients | 288970 |
| 2024-25 unmet % | 33.2 |
| 2024-25 unassisted part 1 | 232.0 |
| 2024-25 unassisted part 2 | 79.4 |
| 2024-25 unassisted part 3 | 41.7 |
| 2024-25 unassisted total (recomputed) | 353.1 |
| 2023-24 clients | 280078 |
| 2023-24 unmet % | 32.8 |
| 2023-24 unassisted part 1 | 208.6 |
| 2023-24 unassisted part 2 | 62.9 |
| 2023-24 unassisted part 3 | 28.5 |
| 2023-24 unassisted total (recomputed) | 300.0 |
| 2022-23 clients | 273648 |
| 2022-23 unmet % | 34.9 |
| 2022-23 unassisted part 1 | 213.6 |
| 2022-23 unassisted part 2 | 58.2 |
| 2022-23 unassisted part 3 | 22.7 |
| 2022-23 unassisted total (recomputed) | 294.5 |
| 2021-22 clients | 272694 |
| 2021-22 unmet % | 33.9 |
| 2021-22 unassisted part 1 | 203.2 |
| 2021-22 unassisted part 2 | 59.9 |
| 2021-22 unassisted part 3 | 24.8 |
| 2021-22 unassisted total (recomputed) | 287.9 |
| 2020-21 clients | 278275 |
| 2020-21 unmet % | 32.3 |
| 2020-21 unassisted part 1 | 226.3 |
| 2020-21 unassisted part 2 | 60.4 |
| 2020-21 unassisted part 3 | 25.7 |
| 2020-21 unassisted total (recomputed) | 312.4 |
