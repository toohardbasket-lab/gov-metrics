# Checking record: Wages and prices

## Status

Two series. No figure is typed or edited by hand. The scraper is `scrapers/wages_and_prices.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `wage_growth` | ABS Data API, dataflow `WPI`, key `3.THRPEB.7.TOT.20.AUS.Q` (percentage change from the corresponding quarter of the previous year, total hourly rates of pay excluding bonuses, private and public sectors, all industries, seasonally adjusted, Australia, quarterly). | `sources/abs-wpi-3.THRPEB.7.TOT.20.AUS.Q.csv` |
| `price_growth` | Copied from the inflation page: series `headline_quarterly` in `metrics/inflation/data.csv` (Reserve Bank table G1, series `GCPIAGYP`), for the quarters from the first wage quarter on. Nothing is downloaded for it and the file is not copied into `sources/`. | the manifest entry `copied-from-metrics-inflation-data.csv` records the path and the checksum of the inflation file at the time of copying |

Second source used only as a check for wages: the ABS Table 1 spreadsheet (`sources/abs-wpi-634501.xlsx`; the address comes from the Wage Price Index "latest release" page each time), sheet Data1, the column with series ID `A83895396W` (found by its series ID; its header text and series type, Seasonally Adjusted, are checked too).

**Blank quarters.** The API response starts with four blank values (OBS_STATUS `u`) for 1997-Q3 to 1998-Q2. The scraper skips blank values that come before the first figure and refuses a blank anywhere after it (a gap).

**Rounding.** The WPI response has no DECIMALS column at all. The scraper accepts a figure only if its own text already has at most one decimal place and writes it with exactly one ("3" becomes "3.0"). A figure with more places is refused, never rounded.

**Price growth.** The validator (`copy_of` in `metric.yml`) checks on every run that each `price_growth` row equals the inflation page's `headline_quarterly` row for the same date. In `run_all.py` the inflation scraper runs first; if it fails, this scraper is skipped and reported as failed. The scraper refuses if the inflation file is missing, has no figure for the first wage quarter, has a quarter missing from there on, or ends before the latest wage quarter.

The check required before publication (plan rule 8.8) is recorded below; it was done by Claude at Alan's request, not by a person.

## What the scraper checked (run of 24 November 2026)

- `wage_growth`: 113 quarters, 1998-Q3 to 2026-Q3, none missing. 4 leading blank quarters (1997-Q3 to 1998-Q2) skipped. Latest value 3.5 (2026-Q3).
- `price_growth`: 113 quarters, 1998-Q3 to 2026-Q3, none missing. Latest value 3.9 (2026-Q3).
- `data.csv`: 226 rows, sorted by series then date. Dates are the last day of the quarter; jurisdiction Australia; unit pct; status actual. Two runs in a row gave a byte-identical `data.csv`.
- Wage cross-check against Table 1, series ID A83895396W (series type Seasonally Adjusted, unit Percent): 113 of 113 quarters agree (1998-Q3 to 2026-Q3), and the latest quarter is 2026-Q3 in both. The two sources also cover exactly the same quarters. Table 1 address: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia/sep-2026/634501.xlsx
- Inflation file used for the copy: `metrics/inflation/data.csv`, sha256 `7afc4da775b7c29ee72bfdaf3fb6e92ac48f34944732b457edfba216598e5ab3` (32257 bytes) at the time of copying.

## Settings in `metric.yml` worth knowing

- No step check on either series: rates can be near zero, so a step as a per cent of the earlier figure means nothing.
- Revision tolerances: wages 0.3 points (seasonally adjusted and re-estimated); prices 0.1 points (not revised, so any change blocks).
- `{latest_period}` in the chart source line names the latest period of `wage_growth` (set by `latest_period_series`). Prices can run one quarter ahead of wages; the table leaves the wage cell blank for such a quarter.
- Government forecast row: "Not yet added". To be filled from the latest Budget or Mid-Year Economic and Fiscal Outlook before publication.

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page (the table at the foot of the page) were compared with official files downloaded again for this check, read by separate code written for the check, not the scraper's code. The latest figure and five other dates chosen at random (fixed seed "2026-11-25-wages-and-prices"). Worked-out figures were recalculated from the official figures. A planted error in a page cell was caught by the same check.

Against: ABS Wage Price Index September 2026 Table 1 (series A83895396W); Reserve Bank table G1 (series GCPIAGYP)

Result: 12 figures compared, all matched.

| Point | Page |
|---|---|
| September 2026 wage growth | 3.5 |
| September 2026 price growth | 3.9 |
| September 2022 wage growth | 3.1 |
| September 2022 price growth | 7.3 |
| December 2022 wage growth | 3.3 |
| December 2022 price growth | 7.9 |
| June 1999 wage growth | 3.1 |
| June 1999 price growth | 1.1 |
| December 2001 wage growth | 3.4 |
| December 2001 price growth | 3.1 |
| September 2013 wage growth | 2.6 |
| September 2013 price growth | 2.2 |
