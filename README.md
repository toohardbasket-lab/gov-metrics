# Government metrics tracker (working title)

This project is a website that will show official Australian government figures, such as debt, housing and homelessness, in one consistent format. Every number comes from an official source and is linked back to it. The name is a working title and will change.

The site is a set of plain files. It has no database and no server to run.

## Running it on your own Windows computer

You need Node.js version 22 installed (the version used to build this is recorded in the `.nvmrc` file). Then, in a terminal opened in this folder:

1. `npm install` downloads what the site needs. You only do this once, or after the list of tools changes.
2. `npm run dev` starts a local copy you can look at in your browser. The terminal prints the address. Press Ctrl+C to stop it.
3. `npm run build` checks the data (see below) and then produces the finished site in a folder called `dist`. If the check finds a problem, the build stops and `dist` is left as it was.

## What is in each folder

- `site.config.mjs`: the one file holding the site name, publisher, authorisation line, contact email, footer text and web address. Change the name or owner here and nowhere else.
- `src/`: the pages, the shared page layout, the chart (`src/components/MetricChart.astro`), the code that reads each metric's files (`src/lib/`) and the styling.
- `metrics/`: one folder per metric, with its definition (`metric.yml`), data and checking notes. The first is `commonwealth-debt`. Its `sources/` folder holds the Treasury files as downloaded and a `manifest.json` that records where and when. See `metrics/README.md` for what goes in `metric.yml`.
- `shared/`: lists used on every chart: `governments.csv` (when each government was sworn in), `events.csv` (the marked events) and `cpi_june.csv` (June quarter price index, used for the inflation-adjusted views). `shared/sources/` holds the raw ABS download and its manifest.
- `scrapers/`: the Python programs that download official data and write the CSV files (`commonwealth_debt.py` and `cpi_june.py`), `run_all.py` and `report.py` (the weekly update and its report), their tests, and `requirements.txt`. See `scrapers/README.md`.
- `scripts/`: the data checker (`validate.mjs`) and its tests.
- `.github/workflows/`: the two automatic jobs on GitHub (see below).
- `public/`: files copied to the site as they are.
- `dist/`: the built site. Created by `npm run build`. Not kept in version history.

## Checking the data

Three commands, all typed in a terminal opened in this folder:

- `npm run validate` checks every metric and the shared files and prints every problem it finds, one line each. It checks that the file layout is right, every date is real, every number is a number inside the range set for that series, no year is missing, nothing is duplicated, no rows have disappeared since the data was last accepted, the downloaded source files are exactly as recorded, and the price index has no gaps. It passes only if everything is right. The build runs it first, so a bad file can never be published. Use it any time you change a data file by hand.
- `npm run accept-data` does the same checks and, only if they all pass, records the current data as accepted (in `metrics/<name>/data.lock.json`). From then on the checker refuses data with fewer rows, or a shorter date range, than that record. Use it after you have checked new figures against the source and are happy with them. If rows were removed on purpose, delete the `data.lock.json` file first, then run it.
- `npm run test:validate` tests the checker itself, by damaging a temporary copy of the data in about 40 ways and confirming each one is caught. Use it after changing `scripts/validate.mjs`.

If `npm run validate` prints a line starting WARNING, nothing is wrong, but the data differs from what was last accepted. Check the changes, then run `npm run accept-data`.

## How changes arrive

Every Monday (22:00 UTC) a job on GitHub, `.github/workflows/weekly-update.yml`, downloads the latest official figures, writes a plain-language report of what changed, runs the checks and the build, and opens a pull request containing the changes and the report. If the checks fail it commits nothing and opens an issue instead. It can also be started by hand from the Actions tab. The job never writes to the main branch: nothing reaches it unless the owner reads the pull request and merges it. A second job, `.github/workflows/check.yml`, runs the tests and a full build on every pull request.

Other changes, such as new pages and code, are sent as patch files. Only the owner applies them.
