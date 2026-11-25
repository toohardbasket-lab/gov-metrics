# Checking record: Budget balance

## Status

Two series stored, one derived view (inflation-adjusted dollars, worked out when the page is built, not stored). No figure is typed or edited by hand. The scraper is `scrapers/budget_balance.py`, which imports the Word-reading helpers of the debt scraper (`scrapers/commonwealth_debt.py`) and finds the Final Budget Outcome the same way (the same web address pattern and the same default year, so a new Final Budget Outcome is picked up the same way as for the debt page). The raw downloads are saved unchanged in `sources/` (they are the same two files the debt page saves), and the web address, date retrieved, checksum and size of each are in `sources/manifest.json`.

| Series | Source | Saved as |
|---|---|---|
| `ucb` | Treasury, Final Budget Outcome 2025-26, Appendix B, Table B.1 ("Australian Government general government sector receipts, payments, net Future Fund earnings and underlying cash balance"), last two columns, "Underlying cash balance" $m. Whole numbers, sign as published (negative is a deficit). Unit `aud_million`. | `sources/fbo-2025-26-appendix-b.docx` |
| `ucb_pct_gdp` | Same table, "Underlying cash balance" per cent of GDP. One decimal. Unit `pct_gdp`. | same file |
| inflation-adjusted view (**derived, not stored**) | `ucb` multiplied by the June CPI of the latest June divided by the June CPI of that year, from `shared/cpi_june.csv`, exactly as on the debt page. | nothing: not in `data.csv` |

Table B.1 is split across two Word tables (1970-71 to 2009-10, then 2010-11 to 2025-26, the second marked "(continued)"). The scraper finds it by its caption, not by position, and **refuses to read it unless every piece has exactly the expected header layout**: twelve columns, with every heading in the expected place (receipts, payments, net Future Fund earnings, underlying cash balance, each with its unit). A renamed heading, a changed unit, or a column added or removed stops the run and nothing is written.

**Cross-check.** The scraper refuses unless the latest year's underlying cash balance equals the "Underlying cash balance" row of the overview table in Part 1 of the same Final Budget Outcome (Table 1.1, column "2025-26 Outcome $b"), rounded the way Part 1 prints it (one decimal place, in $ billion), and the per cent of GDP row beneath it equals the Appendix B share. They matched on the run of 25 November 2026: Appendix B -22,254 $m = -22.3 $b = Part 1 -22.3; per cent of GDP -0.8 = -0.8.

**Rows never fall.** The scraper refuses if a rerun would have fewer rows than the stored `data.csv`.

## What the scraper checked (run of 25 November 2026)

- `data.csv`: 112 rows (2 series x 56 years, 1970-71 to 2025-26), dates 30 June 1971 to 30 June 2026, period like 2025-26, jurisdiction Commonwealth, status actual. A second run gave a byte-identical `data.csv`, manifest and raw files.
- Latest: 2025-26 underlying cash balance -22,254 $m (-0.8 per cent of GDP). Earliest: 1970-71, 901 $m (2.2 per cent of GDP).
- 2022-23: surplus of 22,064 $m (0.9 per cent of GDP). 2023-24: surplus of 15,779 $m (0.6 per cent). The "Read with care" note's example (the 2022-23 surplus) was checked against these figures.
- The scraper's reading of the previous year's file (Final Budget Outcome 2024-25, kept as a test fixture) was compared with this year's: no dollar figure changed in 55 years; one share of GDP changed, by 0.1 point (2017-18, -0.6 to -0.5). The revision comments in `metric.yml` rest on this.

## Settings in `metric.yml` worth knowing

- Revision tolerance: `ucb` `{max_abs: 1}` ($1m), `ucb_pct_gdp` `{max_abs: 0.5}`, as on the debt page. Tested: a one-digit change to a past year (1980-81, -184 to -174) blocks; a sign flip (2023-24) blocks. A change of exactly 1 passes with a warning.
- Plausible ranges: `ucb` -300,000 to 100,000, `ucb_pct_gdp` -15 to 10 (the real extremes are -134,171 $m in 2020-21 and 22,064 $m in 2022-23, and -6.4 and 2.2 per cent of GDP in 2020-21 and 1970-71).
- Every view sets `zero_line: true`, a general view option that draws a clear line at zero (darker and thicker than the gridlines).
- The page is a draft until the check below is done.

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page were compared with Table B.1 of the Final Budget Outcome 2025-26, Appendix B (Word file downloaded again for this check), read by separate code. All 56 years of both stored columns matched. For the latest year and five other years chosen at random (seed "2026-11-25-budget-balance") the June 2026 dollar figure was also recalculated from the ABS quarterly CPI index (Data API, June quarters), independently of `shared/cpi_june.csv`.

Result: all 112 stored figures matched; 18 figures in the detailed sample, including 6 recalculated real-dollar figures, all matched.

| Point | Page |
|---|---|
| 2025-26 UCB $m | -22254 |
| 2025-26 UCB %GDP | -0.8 |
| 2025-26 real $m (recomputed, ABS index) | -22254 |
| 1972-73 UCB $m | 348 |
| 1972-73 UCB %GDP | 0.7 |
| 1972-73 real $m (recomputed, ABS index) | 4342 |
| 1991-92 UCB $m | -12631 |
| 1991-92 UCB %GDP | -3.0 |
| 1991-92 real $m (recomputed, ABS index) | -31154 |
| 2015-16 UCB $m | -39606 |
| 2015-16 UCB %GDP | -2.4 |
| 2015-16 real $m (recomputed, ABS index) | -53706 |
| 2020-21 UCB $m | -134171 |
| 2020-21 UCB %GDP | -6.4 |
| 2020-21 real $m (recomputed, ABS index) | -166449 |
| 2023-24 UCB $m | 15779 |
| 2023-24 UCB %GDP | 0.6 |
| 2023-24 real $m (recomputed, ABS index) | 16745 |
