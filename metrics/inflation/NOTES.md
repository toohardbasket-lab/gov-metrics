# Checking record: Inflation

## Status

Three series, all read by code. No figure is typed or edited by hand. The scraper is `scrapers/inflation.py`; the raw downloads are saved unchanged in `sources/`, and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `headline_quarterly` | Reserve Bank of Australia, table G1, series `GCPIAGYP` (year-ended inflation, all groups, original). Quarters from 1950-Q1; earlier quarters are dropped (the owner's decision: no chart starts before 1950). Stored as published, one decimal. | `sources/rba-g1-data.csv` |
| `trimmed_mean_quarterly` | ABS Data API, dataflow `CPI_Q`, key `3.999902.20.50.Q` (percentage change from the corresponding quarter of the previous year, trimmed mean, seasonally adjusted, weighted average of eight capitals, quarterly). | `sources/abs-cpi_q-3.999902.20.50.Q.csv` |
| `headline_monthly` | ABS Data API, dataflow `CPI`, key `3.10001.10.50.M` (percentage change from the corresponding month of the previous year, all groups, original, weighted average of eight capitals, monthly). | `sources/abs-cpi-3.10001.10.50.M.csv` |

Second sources used only as checks: the ABS quarterly CPI index (`CPI 1.10001.10.50.Q`, `sources/abs-cpi-1.10001.10.50.Q.csv`) and the ABS Table 1 spreadsheet (`sources/abs-cpi-640101.xlsx`; the address comes from the CPI "latest release" page each time).

**Rounding.** The ABS leaves the DECIMALS cell empty for the `CPI` and `CPI_Q` dataflows (the Labour Force dataflow fills it), so "round to DECIMALS" cannot be applied literally. The scraper instead accepts an ABS percentage figure only if its own text already has at most one decimal place and writes it with exactly one ("4" becomes "4.0"). A figure with more places is refused, never rounded. Every figure in the three downloads already has one place or fewer. G1 figures are held to the same rule. The check required before publication (plan rule 8.8) is recorded below; it was done by Claude at Alan's request, not by a person.

## What the scraper checked (run of 24 November 2026)

- `headline_quarterly`: 307 quarters, 1950-Q1 to 2026-Q3, none missing. Latest value 3.9 (2026-Q3).
- `trimmed_mean_quarterly`: 175 quarters, 1983-Q1 to 2026-Q3, none missing. Latest value 3.7 (2026-Q3).
- `headline_monthly`: 18 months, 2025-04 to 2026-09, none missing. Latest value 4.3 (2026-09).
- `data.csv`: 500 rows, sorted by series then date. Dates are the last day of the quarter or month; jurisdiction Australia; unit pct; status actual. Two runs in a row gave a byte-identical `data.csv`.

Cross-checks (all must pass or nothing is written):

1. **Headline quarterly against the ABS index.** For every kept quarter, the year-ended change was worked out in code from the ABS quarterly CPI index, `(index_t / index_(t-4) - 1) * 100` with Python Decimal, rounded half up to one decimal. 307 of 307 quarters agree with G1 exactly (1950-Q1 to 2026-Q3). The latest quarter is 2026-Q3 in both. The worked-out figure is only a check; the stored figure is G1's.
2. **Trimmed mean against G1 series `GCPIOCPMTMYP`.** 175 quarters compared (1983-Q1 to 2026-Q3). All 99 quarters from 2002-Q1 on agree exactly. The latest quarter is 2026-Q3 in both. Before 2002-Q1 the two differ in **34 quarters, by at most 0.2 points** (141 of the 175 agree). The scraper prints each difference and does not refuse for them. The page stores the ABS figure and says so under "Read with care".
3. **Monthly against ABS Table 1.** Column found by its header text ("Percentage Change from Corresponding Month of Previous Year ; All groups CPI ; Australia"; it is the only such column), series ID **A130393721F**, series type Original, unit Percent. 18 months compared (2025-04 to 2026-09), all agree after rounding. The latest month is 2026-09 in both. Table 1 address: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/sep-2026/640101.xlsx

### Trimmed mean, quarters before 2002-Q1 where the ABS and G1 differ

| Quarter | ABS (stored) | G1 | Difference |
|---|---|---|---|
| 1983-Q1 | 10.6 | 10.7 | 0.1 |
| 1983-Q2 | 9.8 | 10.0 | 0.2 |
| 1983-Q3 | 8.3 | 8.5 | 0.2 |
| 1983-Q4 | 7.8 | 7.9 | 0.1 |
| 1984-Q2 | 6.7 | 6.6 | 0.1 |
| 1984-Q3 | 6.3 | 6.2 | 0.1 |
| 1984-Q4 | 5.6 | 5.5 | 0.1 |
| 1985-Q2 | 6.4 | 6.5 | 0.1 |
| 1985-Q3 | 7.4 | 7.5 | 0.1 |
| 1985-Q4 | 8.1 | 8.2 | 0.1 |
| 1986-Q1 | 8.9 | 8.8 | 0.1 |
| 1987-Q3 | 8.1 | 8.2 | 0.1 |
| 1989-Q3 | 6.1 | 6.2 | 0.1 |
| 1990-Q3 | 6.6 | 6.5 | 0.1 |
| 1990-Q4 | 6.7 | 6.6 | 0.1 |
| 1991-Q2 | 5.1 | 5.0 | 0.1 |
| 1991-Q3 | 4.9 | 4.8 | 0.1 |
| 1991-Q4 | 3.8 | 3.7 | 0.1 |
| 1993-Q1 | 2.1 | 2.2 | 0.1 |
| 1993-Q2 | 2.1 | 2.2 | 0.1 |
| 1993-Q3 | 2.1 | 2.3 | 0.2 |
| 1993-Q4 | 2.2 | 2.3 | 0.1 |
| 1994-Q1 | 2.2 | 2.3 | 0.1 |
| 1994-Q2 | 2.2 | 2.3 | 0.1 |
| 1995-Q4 | 3.1 | 3.2 | 0.1 |
| 1996-Q3 | 2.5 | 2.6 | 0.1 |
| 1996-Q4 | 2.3 | 2.4 | 0.1 |
| 1997-Q1 | 2.4 | 2.5 | 0.1 |
| 1997-Q2 | 2.0 | 2.1 | 0.1 |
| 1997-Q3 | 1.7 | 1.8 | 0.1 |
| 1997-Q4 | 1.9 | 2.0 | 0.1 |
| 1999-Q3 | 2.2 | 2.1 | 0.1 |
| 2000-Q1 | 2.6 | 2.5 | 0.1 |
| 2001-Q2 | 2.9 | 3.0 | 0.1 |

## Settings in `metric.yml` worth knowing

- No step check on any series: rates cross zero, so a step as a per cent of the earlier figure means nothing.
- Revision tolerances: headline 0.1 points (headline CPI is not revised, so any change blocks); trimmed mean 0.3 points (seasonally adjusted and re-estimated).
- `{latest_period}` in the chart source line names the latest period of `headline_monthly` (set by `latest_period_series`), because three series end on 30 September 2026.

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page (the table at the foot of the page) were compared with official files downloaded again for this check, read by separate code written for the check, not the scraper's code. The latest figure and five other dates chosen at random (fixed seeds "2026-11-25-inflation-q" and "2026-11-25-inflation-m"), for the quarterly and the monthly series, were checked; worked-out figures were recalculated from the official figures. A planted error in a page cell was caught by the same check.

Against: Reserve Bank table G1 (series GCPIAGYP, GCPIOCPMTMYP); ABS CPI October 2026 Table 1 (series A130393721F); ABS Data API CPI_Q for trimmed mean quarters before 2002

Result: 15 figures compared, all matched.

| Point | Page |
|---|---|
| September 2026 quarterly CPI | 3.9 |
| September 2026 trimmed mean | 3.7 |
| September 2007 quarterly CPI | 1.9 |
| September 2007 trimmed mean | 2.9 |
| March 1976 quarterly CPI | 13.1 |
| September 1999 quarterly CPI | 1.7 |
| September 1999 trimmed mean | 2.2 |
| September 1959 quarterly CPI | 2.2 |
| September 1966 quarterly CPI | 2.6 |
| September 2026 monthly CPI | 4.3 |
| July 2026 monthly CPI | 3.5 |
| August 2025 monthly CPI | 3.2 |
| February 2026 monthly CPI | 3.7 |
| April 2026 monthly CPI | 4.2 |
| December 2025 monthly CPI | 3.8 |
