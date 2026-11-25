# Checking record: New homes

## Status

Five series on the page, two of them stored. No figure is typed or edited by hand. The scraper is `scrapers/new_homes.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `completions` (stored) | ABS Building Activity, Data API dataflow `BUILDING_ACTIVITY`, key `M7.AUS+1+2+3+4+5+6+7+8.CUR.TOT.9.TOT.20.Q`: dwelling unit completions, all sectors, total dwelling types, seasonally adjusted, quarterly, whole numbers (unit `count`). 168 quarters for each of nine jurisdictions, 1984-Q3 to 2026-Q2. | `sources/abs-building_activity-M7.1-8-AUS.CUR.TOT.9.TOT.20.Q.csv` |
| `population_june_2024` (stored, copied) | Copied by the scraper from `metrics/social-housing/data.csv`, series `population`, 30 June 2024, so the rate uses the same population as the social housing page. `copy_of` in `metric.yml` makes the checker block any row that differs from that page. | manifest entry `copied-from-metrics-social-housing-data.csv` (path, series, retrieved, sha256, bytes) |
| `accord_completed` (**derived, not stored**) | Running total of `completions` from the September quarter 2024 (`derive: {type: cumulative_sum, start: 2024-09-30}`). Blank before the start; a quarter with no usable figure blanks every later total. | nothing: not in `data.csv` |
| `accord_per_1000` (**derived, not stored**) | `accord_completed` ÷ the 30 June 2024 population × 1,000, one decimal place, rounded half up (`derive: {type: ratio, denominator_date: 2024-06-30, ...}`). | nothing |
| `pace_line` (**derived, not stored**) | Straight line from 0 on 30 June 2024 to 1,200,000 on 30 June 2029, Australia only, one value per quarter (`derive: {type: straight_line, ...}`). | nothing |

Second sources, used only as checks: the ABS Building Activity time series workbooks, Table 37 (Australia) and Table 38 (states and territories), seasonally adjusted dwelling unit completions, saved as `sources/abs-building-activity-87520037.xlsx` and `sources/abs-building-activity-87520038.xlsx`. They are found among the workbooks linked from the latest release page by the table title containing "Dwelling Unit Completions"; the column is then chosen by its header text and series type "Seasonally Adjusted", and each header must match exactly one column in exactly one workbook. Table 39 is Original (not seasonally adjusted) only and is not used.

**Names.** The scraper also asks for the same address with labels (`sources/abs-building_activity-M7.1-8-AUS.CUR.TOT.9.TOT.20.Q-with-labels.csv`) and refuses unless every code is the expected one (1 New South Wales, 2 Victoria, 3 Queensland, 4 South Australia, 5 Western Australia, 6 Tasmania, 7 Northern Territory, 8 Australian Capital Territory, AUS Australia; measure dwelling unit completions; sector, type of building and work type as above) and the plain and labelled responses hold the same figures.

**Rows never fall.** The scraper refuses if a rerun would have fewer rows, start later or end earlier than the stored file for any jurisdiction.

The check required before publication (plan rule 8.8) is recorded below.

## What the scraper checked (run of 25 November 2026)

- `data.csv`: 1521 rows (9 jurisdictions x 168 quarters = 1512, plus population 9). Dates are the last day of the quarter; period is like 2026-Q2; unit `count`. A second run gave a byte-identical `data.csv`, manifest and raw files.
- **API against the ABS spreadsheets: 9 of 9 jurisdictions agree in all 168 quarters** (1,512 figures). The quarter sets are identical. Series IDs: Australia A83801545R, New South Wales A83801521W, Victoria A83801577J, Queensland A83801529R, South Australia A83801585J, Western Australia A83801561R, Tasmania A83801537R, Northern Territory A83801569J, Australian Capital Territory A83801553R.
- The Australia figure is not the sum of the states (it is a separate seasonally adjusted series), and so is the Australia population (27,194,286 at 30 June 2024, which includes Other Territories).

Latest values:

| Item | Value |
|---|---|
| Australia completions, 2026-Q2 | 47,168 |
| Sum of Australia completions 2024-Q3 to 2026-Q1 | **308,649** (the Council's own wording is "308,000", a rounded figure covering the same period; the two agree) |
| Sum to 2026-Q2 (`accord_completed`) | **355,817** |
| Per 1,000 people (Australia) | 13.1 |
| `pace_line` at 2026-Q2 | 480,000 (8 quarters x 60,000) |

Completed since July 2024 to the June quarter 2026, and per 1,000 residents at 30 June 2024, in the page's fixed order:

| State | Completed | Per 1,000 |
|---|---|---|
| New South Wales | 91,954 | 10.8 |
| Victoria | 112,599 | 16.2 |
| Queensland | 68,694 | 12.3 |
| Western Australia | 42,189 | 14.2 |
| South Australia | 26,625 | 14.1 |
| Tasmania | 4,842 | 8.4 |
| Australian Capital Territory | 7,863 | 16.4 |
| Northern Territory | 1,240 | 4.8 |

These were worked out separately by the scraper in exact fractions (`worked_out`, printed only) and match the page.

## Settings in `metric.yml` worth knowing

- Revision tolerance for `completions`: `{max_abs: 1, max_pct: 3, pct_floor: 100}`. A seasonally adjusted series is revised every quarter, so up to 3 per cent is accepted with a warning. Tested: a 5 per cent change to a past Australia quarter blocks; a 2 per cent change passes with a warning; a population row that differs from the social housing page blocks.
- Plausible ranges (decisions not given in the brief): completions 0 to 100,000; `accord_completed` 0 to 1,500,000; `accord_per_1000` 0 to 100; `pace_line` 0 to 1,200,000.
- Status block: Behind, assessed by the National Housing Supply and Affordability Council, August 2026, due 30 June 2029. The third tile reads from it (`from_status: true`).
- The accord view runs `from: 2024` `to: "2029-06-30"`, with two reference lines (1.2 million solid, 1 million dashed) drawn in the inflation band's target colour, and the pace line dashed.
- `straight_line` counts periods, not days.

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page were compared with the ABS Building Activity spreadsheets (Tables 37 and 38, June quarter 2026) downloaded again for this check and read by separate code. The latest quarter and five other quarters chosen at random (seed "2026-11-25-new-homes") were checked, and every state's figures in the panel table. Running totals, the straight-line pace and the per-1,000 figures were recalculated from the official figures, using ABS estimated resident population at 30 June 2024 fetched again from the ABS Data API.

Result: 24 figures compared (blank cells before July 2024 not counted), all matched.

| Point | Page |
|---|---|
| June 2026 completed in quarter | 47168 |
| June 2026 since July 2024 (recomputed) | 355817 |
| June 2026 pace (recomputed) | 480000 |
| March 1990 completed in quarter | 40388 |
| September 2018 completed in quarter | 57205 |
| March 2005 completed in quarter | 40376 |
| September 1998 completed in quarter | 36769 |
| March 1993 completed in quarter | 40057 |
| New South Wales since July 2024 (recomputed) | 91954 |
| New South Wales per 1,000 (recomputed) | 10.8 |
| Victoria since July 2024 (recomputed) | 112599 |
| Victoria per 1,000 (recomputed) | 16.2 |
| Queensland since July 2024 (recomputed) | 68694 |
| Queensland per 1,000 (recomputed) | 12.3 |
| Western Australia since July 2024 (recomputed) | 42189 |
| Western Australia per 1,000 (recomputed) | 14.2 |
| South Australia since July 2024 (recomputed) | 26625 |
| South Australia per 1,000 (recomputed) | 14.1 |
| Tasmania since July 2024 (recomputed) | 4842 |
| Tasmania per 1,000 (recomputed) | 8.4 |
| Australian Capital Territory since July 2024 (recomputed) | 7863 |
| Australian Capital Territory per 1,000 (recomputed) | 16.4 |
| Northern Territory since July 2024 (recomputed) | 1240 |
| Northern Territory per 1,000 (recomputed) | 4.8 |
