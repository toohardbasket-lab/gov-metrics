# Checking record: Commonwealth government debt

## Status

The figures in `data.csv` are parsed by code from Treasury's own Word file, Final Budget Outcome 2025-26, Appendix B (Tables B.4 and B.5), saved unchanged in `sources/fbo-2025-26-appendix-b.docx`. The web address, date retrieved and checksum of each source file are in `sources/manifest.json`.

The scraper (`scrapers/commonwealth_debt.py`) refuses to write anything unless the latest year's gross and net debt match the overview table in Part 1 of the same Final Budget Outcome (`sources/fbo-2025-26-part-1.docx`). They matched when it was last run.

The owner checked the latest year on 17 November 2026 (see below). The plan asks for the latest value and five other points checked by a person; the five other points were checked by Claude on 25 November 2026 at Alan's request (see the end of this file).

The inflation-adjusted views use `shared/cpi_june.csv`, which the ABS scraper (`scrapers/cpi_june.py`) writes from the ABS Data API.

## Human check

Checked by: Alan Hewitt

Date: 17 November 2026

Points checked: 2025-26, all four figures (net debt 549,969 $m and 18.8 per cent of GDP from Table B.4; gross debt 971,447 $m and 33.2 per cent of GDP from Table B.5, "Total AGS on issue"), read from the Word file and compared with the page's table. All matched.

Five other years: checked by Claude, not by a person, on 25 November 2026 (see below).

## Machine checks (not a substitute for the human check)

- 16 November 2026, Claude: compared screenshots of Tables B.4 and B.5 from the Word file with a screenshot of the page's table for 1970-71 to 2009-10. 40 years, four figures each, 160 figures, no differences. This is a model reading images, so it counts as a machine check.
- 16 November 2026, Claude: a separate short script read eight years straight from the Word file (1971-72, 1974-75, 2006-07, 2007-08, 2008-09, 2019-20, 2024-25, 2025-26). All matched `data.csv`.
- 16 November 2026: the scraper's parser was run on the previous year's file (Final Budget Outcome 2024-25) and compared with figures a language model had earlier read from the PDF. 220 of 220 matched.

## Check under plan rule 8.8: done by Claude, not by a person

At Alan's request (25 November 2026: "You do the checks"), this check was done by Claude, the lead model, not by a person.

Date: 25 November 2026

Method: the figures shown on the built page (the table at the foot of the page) were compared with official files downloaded again for this check, read by separate code written for the check, not the scraper's code. Five years other than 2025-26 (which Alan checked on 17 November 2026), chosen at random with the fixed seed "2026-11-25-commonwealth-debt", were checked; worked-out figures were recalculated from the official figures. A planted error in a page cell was caught by the same check.

Against: Treasury, Final Budget Outcome 2025-26, Appendix B, Tables B.4 and B.5 (Word file, downloaded again on 25 November 2026)

Result: 20 figures compared, all matched.

| Point | Page |
|---|---|
| 1987-88 gross $m | 62794 |
| 1987-88 gross %GDP | 19.3 |
| 1987-88 net $m | 27344 |
| 1987-88 net %GDP | 8.4 |
| 1974-75 gross $m | 14785 |
| 1974-75 gross %GDP | 20.7 |
| 1974-75 net $m | -1901 |
| 1974-75 net %GDP | -2.7 |
| 2015-16 gross $m | 420420 |
| 2015-16 gross %GDP | 25.3 |
| 2015-16 net $m | 303467 |
| 2015-16 net %GDP | 18.2 |
| 2007-08 gross $m | 55442 |
| 2007-08 gross %GDP | 4.7 |
| 2007-08 net $m | -39958 |
| 2007-08 net %GDP | -3.4 |
| 1995-96 gross $m | 110166 |
| 1995-96 gross %GDP | 20.8 |
| 1995-96 net $m | 95831 |
| 1995-96 net %GDP | 18.1 |
