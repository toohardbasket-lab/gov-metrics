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
- `metrics/`: one folder per metric, with its definition (`metric.yml`), data and checking notes. The first is `commonwealth-debt`; the second is `unemployment-rate`; the third is `inflation`; the fourth is `wages-and-prices`; the fifth is `rents`; the sixth is `social-housing`; the seventh is `hospital-waits`; the eighth is `homelessness`. Its `sources/` folder holds the Treasury files as downloaded and a `manifest.json` that records where and when. See `metrics/README.md` for what goes in `metric.yml`.
- `shared/`: lists used on every chart: `governments.csv` (when each government was sworn in), `events.csv` (the marked events) and `cpi_june.csv` (June quarter price index, used for the inflation-adjusted views). `shared/sources/` holds the raw ABS download and its manifest.
- `scrapers/`: the Python programs that download official data and write the CSV files (`commonwealth_debt.py`, `cpi_june.py`, `unemployment_rate.py`, `inflation.py`, `wages_and_prices.py` and `rents.py`, `rogs.py`, `social_housing.py`, `hospital_waits.py` and `homelessness.py`), `run_all.py` and `report.py` (the weekly update and its report), their tests, and `requirements.txt`. See `scrapers/README.md`.
- `scripts/`: the data checker (`validate.mjs`) and its tests.
- `.github/workflows/`: the two automatic jobs on GitHub (see below).
- `public/`: files copied to the site as they are.
- `dist/`: the built site. Created by `npm run build`. Not kept in version history.

## Checking the data

Three commands, all typed in a terminal opened in this folder:

- `npm run validate` checks every metric and the shared files and prints every problem it finds, one line each. It checks that the file layout is right, every date is real, every number is a number inside the range set for that series, no year is missing, nothing is duplicated, no rows have disappeared since the data was last accepted, the downloaded source files are exactly as recorded, and the price index has no gaps. It passes only if everything is right. The build runs it first, so a bad file can never be published. Use it any time you change a data file by hand.
- `npm run accept-data` does the same checks and, only if they all pass, records the current data as accepted (in `metrics/<name>/data.lock.json`, which keeps every accepted figure). From then on the checker refuses data with fewer rows, or a shorter date range, than that record, and refuses any large change to a figure that was already accepted (see below). Use it after you have checked new figures against the source and are happy with them. If rows were removed on purpose, delete the `data.lock.json` file first, then run it.
- `npm run accept-data -- --accept-revisions` (or the shorter `npm run accept-revisions`, which does the same) is the one command that accepts large changes to past figures. It lists each change it accepts. Every other problem still stops it.
- `npm run test:validate` tests the checker itself, by damaging a temporary copy of the data in about 75 ways and confirming each one is caught. Use it after changing `scripts/validate.mjs`.

If `npm run validate` prints a line starting WARNING, nothing is wrong, but the data differs from what was last accepted. Check the changes, then run `npm run accept-data`.

Past figures are protected. Each series in `metric.yml` says how far an already accepted figure may change (its `revision` setting, explained in `metrics/README.md`). A small change, such as Treasury moving a share of GDP by 0.2 points, only gives a warning. A bigger change, or a figure that flips from negative to positive, stops the build until you have checked it against the source and accepted it with `npm run accept-data -- --accept-revisions`. A new year added at the end is not a revision.

If the lock file is in the old format (it does not hold the accepted figures), `npm run validate` fails and says so. Run `npm run accept-data` once to upgrade it.

## How changes arrive

Every Monday (22:00 UTC) a job on GitHub, `.github/workflows/weekly-update.yml`, downloads the latest official figures, writes a plain-language report of what changed, runs the checks and the build, and opens a pull request containing the changes and the report. If the checks fail it commits nothing and opens an issue instead. It can also be started by hand from the Actions tab. The job never writes to the main branch: nothing reaches it unless the owner reads the pull request and merges it. A second job, `.github/workflows/check.yml`, runs the tests and a full build on every pull request.

Other changes, such as new pages and code, are sent as patch files. Only the owner applies them.

## When the weekly job opens a pull request

A pull request is a proposed change that waits for you to look at it. The weekly job opens one when the official figures have changed.

1. Open the pull request on GitHub (the weekly job's email, or the Pull requests tab).
2. If the "Check" shows as waiting for approval, click "Approve and run" and wait for the green tick. GitHub holds the checks on pull requests opened by the bot until the owner approves them.
3. Read the report in the pull request's description. It lists new figures, revised figures, anything removed and any source that failed. A revised figure that changed by more than its allowed amount starts with **LARGE:**.
4. Check the new and revised figures against the source (the official file or page that the report names).
5. If they are right, merge the pull request. If anything looks wrong, close it without merging and delete the branch (GitHub offers a "Delete branch" button).
6. On your PC, run `git pull` before applying any new patch, so your copy has the merged data.

## When the weekly job is blocked

If the new data fails the checks, the job commits nothing and opens (or updates) an issue called "Weekly update blocked: validation failed". The issue shows what the checker printed. Nothing has changed on the site and nothing needs undoing.

Read the checker's lines. Most problems mean the source has changed in a way that needs a person to look at it. If a line says a past figure changed by more than its allowed revision, check that figure against the source. If the change is genuine, accept it on your PC:

1. Run `git pull`, then run the scrapers on your PC with `python3 scrapers/run_all.py --status status.json`, so the new data is in your copy. Delete `status.json` afterwards.
2. Run `npm run accept-data -- --accept-revisions`. It prints each large revision it accepts.
3. Commit the changed files, including `data.lock.json`, and push them.

If the figure is wrong, do not accept it. Tell whoever looks after the scraper, because the source file or the reading of it needs fixing.
