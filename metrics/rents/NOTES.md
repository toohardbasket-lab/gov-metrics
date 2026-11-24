# Checking record: Rents

## Status

Three series on the page, two of them stored. No figure is typed or edited by hand. The scraper is `scrapers/rents.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `rents_index_quarterly` (stored) | ABS Data API, dataflow `CPI`, key `1.115522.10.50.Q`: index numbers, rents, original, eight capitals, quarterly. | `sources/abs-cpi-1.115522.10.50.Q.csv` |
| `rents_quarterly` (**derived, not stored**) | Worked out when the page is built and when the data is checked, from `rents_index_quarterly`: (index this quarter ÷ index four quarters earlier − 1) × 100, rounded half up to one decimal place (a tie goes away from zero). Declared in `metric.yml` as `derive: {type: year_ended_change, from: rents_index_quarterly, lag: 4}`. The code is `src/lib/derive.mjs`, used by both the checker and the page. A quarter with no index four quarters earlier has no figure. | nothing: it is not in `data.csv` |
| `rents_monthly`, jurisdiction Australia (stored) | ABS Data API, key `3.115522.10.50.M`: published change over twelve months, rents, original, eight capitals, monthly. | `sources/abs-cpi-3.115522.10.50.M.csv` |
| `rents_monthly`, one jurisdiction per state or territory (stored) | ABS Data API, key `3.115522.10.1+2+3+4+5+6+7+8.M`: the same measure for each capital city. The jurisdiction column holds the state or territory (New South Wales for Sydney, and so on); the city name for display is in `state_panel_config` in `metric.yml`. | `sources/abs-cpi-3.115522.10.1-8.M.csv` |

Second sources, used only as checks (the addresses come from the CPI "latest release" page each time):

- Table 18 (`sources/abs-cpi-6401018.xlsx`), sheet Data1, series ID `A2331876F` ("Index Numbers ; Rents ; Australia ;", Original, unit Index Numbers). The sheet has a second column with the same header, `A2326431V`, which holds the same figures except in two quarters (1998-Q4: 44.31 here, 44.32 there; 1999-Q2: 44.89 here, 44.90 there). The API agrees with `A2331876F` in every quarter. The scraper uses only `A2331876F`, the one named in the plan.
- Table 3 (`sources/abs-cpi-640103.xlsx`), sheet Data1, series ID `A130390095C` (header contains "Percentage Change from Corresponding Month of Previous Year ; Rents ; Australia", Original, unit Percent). A second column, `A130397971V`, has the same header and the same figures; it is not used.
- Table 11 (`sources/abs-cpi-6401011.xlsx`), sheets Data1 to Data4 (the cities are spread across the sheets): for each city two Original columns have the header "Percentage Change from Corresponding Month of Previous Year ; Rents ; <city> ;". Both are read; they must hold the same figures and both must equal the API.

**Region names.** The plain city response has only region codes. The same address asked for with labels (`Accept: application/vnd.sdmx.data+csv;labels=both`) gives "code: name", saved as `sources/abs-cpi-3.115522.10.1-8.M-with-labels.csv`. The scraper refuses unless 1 is Sydney, 2 Melbourne, 3 Brisbane, 4 Adelaide, 5 Perth, 6 Hobart, 7 Darwin and 8 Canberra, and unless the labelled response holds exactly the same figures as the plain one. (The CPI codelist itself was not fetched: it is not one of the addresses this build was allowed to use.)

**Rounding.** The ABS leaves the DECIMALS cell empty for these series. The index is accepted only if the API's own text has at most two decimal places and is written with exactly two ("7.4" becomes "7.40"); the percentage figures at most one, written with exactly one. A figure with more places is refused, never rounded. The page shows the index with one decimal unless the second is not zero (103.3, 7.07).

**Index base.** The API's reference base period is September 2025 = 100.0. If the ABS re-bases the index, every quarter changes and each must be accepted once with `npm run accept-data -- --accept-revisions`.

The page is a draft until the human check below is done.

## What the scraper checked (run of 24 November 2026)

- `rents_index_quarterly` (Australia): 217 quarters, 1972-Q3 to 2026-Q3, none missing. First 7.07, latest 103.30 (2026-Q3).
- `rents_monthly` (Australia): 39 months, 2023-07 to 2026-09, none missing. Latest 3.6 (2026-09).
- `rents_monthly` by state or territory (capital city), each 39 months, 2023-07 to 2026-09, none missing. Latest figures, in the page's fixed order: New South Wales (Sydney) 3.5, Victoria (Melbourne) 2.5, Queensland (Brisbane) 4.6, Western Australia (Perth) 5.3, South Australia (Adelaide) 4.0, Tasmania (Hobart) 3.2, Australian Capital Territory (Canberra) 1.4, Northern Territory (Darwin) 6.5.
- `data.csv`: 568 rows (217 + 39 + 312), sorted by series, jurisdiction, then date. Dates are the last day of the quarter or month; unit `index` for the index and `pct` for the rest; status actual. Two runs in a row gave a byte-identical `data.csv` and identical raw files.
- Table 18, series `A2331876F`: 217 of 217 quarters agree (1972-Q3 to 2026-Q3); the two sources cover exactly the same quarters and the latest quarter is 2026-Q3 in both.
- Table 3, series `A130390095C`: 39 of 39 months agree (2023-07 to 2026-09); same months; latest 2026-09 in both.
- Table 11, each city (39 of 39 months agree with both columns, 2023-07 to 2026-09, and the two columns agree with each other; latest 2026-09 in all three). Series IDs used: Sydney `A130392587K` and `A130390459F`; Melbourne `A130397628K` and `A130390466C`; Brisbane `A130398800V` and `A130399255T`; Adelaide `A130398807K` and `A130399262R`; Perth `A130392594J` and `A130395527L`; Hobart `A130396276X` and `A130394386A`; Darwin `A130392601V` and `A130397978K`; Canberra `A130395219K` and `A130394393X`.
- Worked out from the index (not stored): 213 quarters, 1973-Q3 to 2026-Q3. Smallest -1.5, largest 16.7. The latest, 2026-Q3, is **3.6**: (103.30 ÷ 99.74 − 1) × 100 = 3.569, rounded to 3.6. The two index values are 103.30 (2026-Q3) and 99.74 (2025-Q3). All 213 figures were also worked out separately in Python (exact fractions, `scrapers/rents.py`) and matched the checker's and the page's figures, and 212 of 213 match a plain Decimal calculation (the other, 2021-Q2, is "0.0" here and "-0.0" there).

## Settings in `metric.yml` worth knowing

- `rents_index_quarterly` plausible 1 to 500, revision tolerance 0.01 (the CPI is not revised, so any change to a past figure blocks until the owner accepts it). `rents_monthly` plausible -20 to 40, revision 0.1. The derived series is checked against plausible -20 to 40 (its real range is -1.5 to 16.7).
- No step check: the series pass through zero.
- `{latest_period}` in the chart source line names the latest period of `rents_monthly` (set by `latest_period_series`).
- The state and territory panel (`state_panel: true`, `state_panel_config`): places in the fixed order NSW, Vic, Qld, WA, SA, Tas, ACT, NT; the checker refuses any other order. The panel's note says the ABS publishes city figures only from July 2023.
- No numeric target, so no status chip.

## Human check (plan rule 8.8)

Checked by:

Date:

Against:

Points checked:
