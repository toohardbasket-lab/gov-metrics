# Checking record: Social housing

## Status

Seven series on the page, five of them stored. No figure is typed or edited by hand. The scraper is `scrapers/social_housing.py`, which uses the reusable Report on Government Services loader `scrapers/rogs.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `public_housing` (stored) | Productivity Commission, Report on Government Services (RoGS) 2026, section 18 Housing, table 18A.3, Measure "Descriptive data", Description1 "Public housing". Dwellings at 30 June. | `sources/rogs-202606-partg-section18-housing-dataset.csv` |
| `somih` (stored) | Same table, Description1 "State owned and managed Indigenous housing". | same file |
| `community_housing` (stored) | Same table, Description1 "Community housing", Description3 "Number of Tenancy (Rental) Units" (the Commission's national total uses tenancy units; "Number of dwellings" is a different, smaller count and is NOT used). | same file |
| `indigenous_community_housing` (stored) | Same table, Description1 "Indigenous community housing". | same file |
| `population` (stored) | ABS Data API, dataflow `ERP_Q`, key `1.3.TOT.AUS+1+2+3+4+5+6+7+8.Q`: estimated resident population, persons, all ages, quarterly; the June quarters from 2016. | `sources/abs-erp_q-1.3.TOT.1-8-AUS.Q.csv` |
| `total_social_housing` (**derived, not stored**) | Worked out when the page is built and when the data is checked: the sum of the four dwelling series for each jurisdiction and year (`derive: {type: sum, ...}`). `..` (not applicable) and nil count as zero; `na` or `np` in any part, or a missing part, leaves the total blank. | nothing: not in `data.csv` |
| `per_1000_people` (**derived, not stored**) | Total ÷ population × 1,000, rounded half up to one decimal place (`derive: {type: ratio, ...}`). Blank if either is blank. | nothing: not in `data.csv` |

Second sources, used only as checks:

- The RoGS Excel tables (`sources/rogs-202606-partg-section18-housing-data-tables.xlsx`), sheet "Table 18A.3". The sheet has a different layout from the CSV: the block label (for example "Public housing") is in column A, community housing has a second label ("Number of Tenancy (Rental) Units" or "Number of dwellings") in column B, the year is in column C, the unit in column L, and the jurisdictions in columns M to U with footnote marks in their headings ("NSW (c)"). The loader finds the sheet by its name, the rows by their labels, and the columns by their (cleaned) headings.
- The ABS time series workbook of the same population figures (`sources/abs-erp-310104.xlsx`, Table 4 of the March 2026 release). It is found by its column headers "Estimated Resident Population ; Persons ; <State> ;" among the 3101....xlsx workbooks linked from the "latest release" page; exactly one workbook has them.

**Region names.** The plain response has only region codes. The same address asked for with labels gives "code: name", saved as `sources/abs-erp_q-1.3.TOT.1-8-AUS.Q-with-labels.csv`. The scraper refuses unless 1 is New South Wales, 2 Victoria, 3 Queensland, 4 South Australia, 5 Western Australia, 6 Tasmania, 7 Northern Territory, 8 Australian Capital Territory and AUS Australia, and unless the measure is "Estimated Resident Population", the sex "Persons", the age "All ages", and the labelled response holds exactly the same figures as the plain one. (The ABS code list itself was not fetched; the labelled response is the API's own statement of the names.)

**Codes.** The Commission's codes are stored as codes in `data.csv` (`..`, `na`, `np`, and `-` for nil; the en dash is written as a hyphen), never as zero. The metric decides what they mean: in the total, `..` and nil count as zero and `na` or `np` leave the total blank. A figure that turns into a code, or a code into a figure, is always a revision the checker blocks until it is accepted.

**History.** Each RoGS edition carries ten years. When a later edition drops the earliest year, the scraper keeps the stored rows for that year unchanged and takes the years in both from the new edition; the checker's revision test (2 per cent) then decides whether a change to a past figure is accepted. `sources/manifest.json` holds a `rogs-editions` entry that records, for each stored year, the edition it last came from (all ten years are from the 2026 edition now). The raw files of an older edition stay in `sources/` and in the manifest.

The check required before publication (plan rule 8.8) is recorded below; it was done by Claude at Alan's request, not by a person.

## What the scraper checked (run of 24 November 2026)

- RoGS edition found: 2026 (the newest year on the RoGS front page; its data-downloads page has the housing section, so no fall back to 2025 was needed).
- Table 18A.3, years 2016 to 2025 (10 years, none missing), nine columns (NSW, Vic, Qld, WA, SA, Tas, ACT, NT, Aust), exactly one CSV row per year and selection for each of the four series.
- **CSV against the Excel tables: 360 of 360 figures agree** (4 series x 10 years x 9 columns; 90 each), including every code.
- `data.csv`: 450 rows (4 dwelling series x 9 jurisdictions x 10 years = 360, plus population 9 x 10 = 90), sorted by series, jurisdiction, then date. Dates are 30 June of the year; the period is the year; unit `count`; status actual. Two runs in a row gave a byte-identical `data.csv`, manifest and raw files.
- Population, API: 179 quarters per region (1981-Q3 to 2026-Q1), none missing. The page uses the 10 June quarters 2016 to 2025 (the June 2026 quarter is not published yet).
- **ABS API against the ABS spreadsheet (Table 4): 9 of 9 regions agree in all 179 quarters, including all 44 June quarters of each (396 June-quarter figures in all);** the latest quarter is 2026-Q1 in both. (The spreadsheet also holds 1981-Q2, which the API does not; it is ignored.) Series IDs: New South Wales A2060843J, Victoria A2060844K, Queensland A2060845L, South Australia A2060846R, Western Australia A2060847T, Tasmania A2060848V, Northern Territory A2060849W, Australian Capital Territory A2060850F, Australia A2060842F.

Latest values, Australia, 30 June 2025 (and 2016 for comparison):

| Series | 2016 | 2025 |
|---|---|---|
| Public housing | 320,041 | 296,541 |
| State owned and managed Indigenous housing | 9,949 | 17,163 |
| Community housing (tenancy units) | 80,226 | 118,425 |
| Indigenous community housing | 15,461 | 18,478 |
| Population | 24,190,907 | 27,601,739 |

- **The 2025 Australia total is 450,607** (296,541 + 17,163 + 118,425 + 18,478), which **equals the Commission's 450,607**. Per 1,000 people: 450,607 ÷ 27,601,739 × 1,000 = **16.3**.
- 2025 per 1,000 people by state, in the page's fixed order: New South Wales 18.3, Victoria 12.2, Queensland 13.3, Western Australia 14.5, South Australia 24.5, Tasmania 27.2, Australian Capital Territory 25.5, Northern Territory 48.2. (Totals: 157,171; 86,048; 75,582; 44,238; 46,678; 15,739; 12,343; 12,808.) These were worked out separately in Python (exact fractions) and match the page.
- State owned and managed Indigenous housing is `..` (not applicable, so counted as zero) in **Victoria, Western Australia and the Australian Capital Territory**, in every year 2016 to 2025.
- One `na` (not available): state owned and managed Indigenous housing, **Northern Territory, 2016**. So the Northern Territory total and rate for 2016 are blank, and the Northern Territory chart starts in 2017. The Australia figure for that part in 2016 (9,949) is the sum of the states without the Northern Territory (14,921 in 2017), so the **2016 Australia total (425,677; the Australia rate for 2016 is 17.6) leaves out the Northern Territory's state owned and managed Indigenous dwellings** and is not strictly comparable with later years. The page cannot say this in its fixed text; the owner may want a line about it.
- For every dwelling series the eight states and territories add up to the Australia figure in every year (with `..` as zero, and 2016 SOMIH without the NT). The population states do not add up to Australia: Australia includes Other Territories (about 5,000 people), so the Australia rate is worked out from the Australia population, as the Commission and the ABS publish it.
- The Commission's own notes (table 18A.3, footnotes) record transfers between types that move dwellings from one type to another, for example NSW public housing to community housing in 2018-19 and 2019-20 and to SOMIH in 2023-24 and 2024-25, SA in 2017-18 and Tasmania in 2021-22; and Queensland's community housing includes pre-1996 rental units from 2021. These explain the big year-to-year moves in single series.

## Settings in `metric.yml` worth knowing

- Revision tolerances. The brief asked for `{max_pct: 2, pct_floor: 100}` for dwellings and `{max_pct: 1}` for population. The checker requires `max_abs` (a number above zero) in every revision setting, so each has `max_abs: 1`: a change blocks only if it is more than 1 and more than the per cent limit, which is the per cent limit alone for counts of 100 or more and "more than 1" below 100 (dwellings). Population: any change of more than 1 person and more than 1 per cent. Tested: a 5 per cent change to a past public housing count blocks; 1 per cent passes with a warning.
- Plausible ranges: dwellings 0 to 1,000,000; population 0 to 40,000,000; the worked-out total 0 to 1,000,000; the worked-out rate 0 to 200 (the real range is about 12.2 to 51.2 per 1,000). No step check.
- The state panel series is the derived `per_1000_people`; its extra column is the derived total. Chart lines: five on the dwellings view, colours 1 to 5 (blue, orange, plum, green, violet).

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page (the table at the foot of the page) were compared with official files downloaded again for this check, read by separate code written for the check, not the scraper's code. The latest figure and five other dates chosen at random (fixed seed "2026-11-25-social-housing"). Worked-out figures were recalculated from the official figures. A planted error in a page cell was caught by the same check.

Against: Productivity Commission RoGS 2026 section 18 dataset, table 18A.3; ABS Data API ERP_Q (population)

Result: 42 figures compared, all matched.

| Point | Page |
|---|---|
| 2025 public | 296541 |
| 2025 community | 118425 |
| 2025 SOMIH | 17163 |
| 2025 ICH | 18478 |
| 2025 total (recomputed) | 450607 |
| 2025 population | 27601739 |
| 2025 per 1,000 (recomputed) | 16.3 |
| 2022 public | 297600 |
| 2022 community | 112843 |
| 2022 SOMIH | 14291 |
| 2022 ICH | 16302 |
| 2022 total (recomputed) | 441036 |
| 2022 population | 26018721 |
| 2022 per 1,000 (recomputed) | 17.0 |
| 2019 public | 305191 |
| 2019 community | 100205 |
| 2019 SOMIH | 14662 |
| 2019 ICH | 16193 |
| 2019 total (recomputed) | 436251 |
| 2019 population | 25334826 |
| 2019 per 1,000 (recomputed) | 17.2 |
| 2017 public | 319913 |
| 2017 community | 82902 |
| 2017 SOMIH | 14921 |
| 2017 ICH | 16030 |
| 2017 total (recomputed) | 433766 |
| 2017 population | 24592588 |
| 2017 per 1,000 (recomputed) | 17.6 |
| 2018 public | 316231 |
| 2018 community | 87819 |
| 2018 SOMIH | 14686 |
| 2018 ICH | 15766 |
| 2018 total (recomputed) | 434502 |
| 2018 population | 24963258 |
| 2018 per 1,000 (recomputed) | 17.4 |
| 2020 public | 300403 |
| 2020 community | 103895 |
| 2020 SOMIH | 14639 |
| 2020 ICH | 15053 |
| 2020 total (recomputed) | 433990 |
| 2020 population | 25649248 |
| 2020 per 1,000 (recomputed) | 16.9 |
