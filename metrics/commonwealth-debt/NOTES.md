# Checking record: Commonwealth government debt

## Status

The figures in `data.csv` are parsed by code from Treasury's own Word file, Final Budget Outcome 2025-26, Appendix B (Tables B.4 and B.5), saved unchanged in `sources/fbo-2025-26-appendix-b.docx`. The web address, date retrieved and checksum of each source file are in `sources/manifest.json`.

The scraper (`scrapers/commonwealth_debt.py`) refuses to write anything unless the latest year's gross and net debt match the overview table in Part 1 of the same Final Budget Outcome (`sources/fbo-2025-26-part-1.docx`). They matched when it was last run.

The figures are still awaiting the owner's check. The page stays in draft until the check below is done.

The inflation-adjusted views use `shared/cpi_june.csv`, which the ABS scraper (`scrapers/cpi_june.py`) writes from the ABS Data API.

## Human check (owner to fill in)

Checked by:

Date:

Points checked (latest value and five others, against the source):

