# Scrapers

Scrapers are written in Python. Each one downloads an official source file, saves the raw file under the metric's `sources/` folder, and writes a versioned `data.csv`. There is no scraper code yet.

Every scraper must follow the nine data rules from the build plan, in plain words:

1. Never type a figure. Every number comes from a file the scraper downloaded. The metric's definition file records the web address, the table, the date retrieved and a checksum of the file.
2. One folder per metric, holding `metric.yml`, `data.csv`, `sources/` (raw files as downloaded) and `NOTES.md`.
3. Use the long CSV shape (`date, series, jurisdiction, value, unit, status, period`). Status is `actual`, `estimate` or `forecast`. Dates are real dates, and the source's own period label goes in `period`.
4. Check the data before publishing, and refuse to publish if a check fails: no missing years inside a series; values inside a stated sensible range; the latest value matches a second official statement of the same figure where one exists; and the row count never falls between runs.
5. Work out derived figures (inflation-adjusted dollars, per person, straight-line pace) in code, label them as derived, and print the formula on the page.
6. Keep revisions. When a source revises its history, the old CSV stays in version history and the page notes that figures were revised and when.
7. Disclose conflicts. If two official sources disagree, show both and say so.
8. A person checks every new page before it is first published. They check the latest value and five other points against the source, and initial the metric's `NOTES.md`. A page without that check stays in draft.
9. A reading model is not a parser. Read the source file in code (the Excel or CSV version where one exists), then have a person spot-check it. Reading a PDF with a language model is only good enough for a prototype.
