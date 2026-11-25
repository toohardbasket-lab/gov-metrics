# Checking record: Unemployment rate

## Status

The figures in `data.csv` are read by code from the ABS Data API (dataflow `ABS,LF`, key `M13.3.1599.20.AUS.M`: unemployment rate, persons, all ages 15 and over, seasonally adjusted, Australia, monthly). The response is saved unchanged in `sources/abs-lf-M13.3.1599.20.AUS.M.csv`. Each value is the API's figure rounded to the number of decimal places in its own DECIMALS column (1), half up, in code. No figure is typed or edited by hand.

The scraper (`scrapers/unemployment_rate.py`) also downloads the ABS Labour Force spreadsheet, Table 1 (`sources/abs-lf-62020001.xlsx`; the address comes from the Labour Force "latest release" page each time), reads column A84423050A ("Unemployment rate ; Persons ;", seasonally adjusted) and refuses to write anything unless every month in both agrees after the same rounding and both end on the same month. The web address, date retrieved and checksum of each source file are in `sources/manifest.json`.

The human check (plan rule 8.8) was done by Alan on 23 November 2026; see below.

## What the scraper checked (run of 23 November 2026)

- Rows: 585 months, none missing.
- First month: 1978-02. Last month: 2026-10.
- Latest value: 4.9 (October 2026). The same month a year earlier, October 2025: 4.3.
- Spreadsheet cross-check, series A84423050A: 585 months compared (1978-02 to 2026-10), all agree; the latest month is 2026-10 in both.
- Two runs in a row gave a byte-identical `data.csv`.
- Largest month-to-month move in the series: 1.1 points, 5.2 to 6.3 per cent, March to April 2020 (21 per cent of 5.2). The step limit in `metric.yml` is 35 per cent.

## Review by the lead model (23 November 2026)

- All 585 values match a separate download of the same ABS series taken earlier the same day, rounded independently. Every date is the last day of its month and matches its period label.
- This is a machine check, not the human check below.

## Human check (plan rule 8.8): done

Checked by: Alan Hewitt

Date: 23 November 2026

Against: ABS, Labour Force, Australia, October 2026, Table 1 spreadsheet (62020001.xlsx), sheet Data1, series A84423050A (unemployment rate, persons, seasonally adjusted), rounded to one decimal place.

Points checked, all matched the page:

| Month | Page |
|---|---|
| 2026-10 (latest) | 4.9 |
| 2025-11 | 4.3 |
| 2023-08 | 3.7 |
| 2021-03 | 5.7 |
| 2018-05 | 5.4 |
| 2016-10 | 5.6 |

Still open before publication: the government forecast row in `metric.yml` says "Not yet added".
