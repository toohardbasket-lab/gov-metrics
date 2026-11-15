# Government metrics tracker (working title)

This project is a website that will show official Australian government figures, such as debt, housing and homelessness, in one consistent format. Every number comes from an official source and is linked back to it. The name is a working title and will change.

The site is a set of plain files. It has no database and no server to run.

## Running it on your own Windows computer

You need Node.js version 22 installed (the version used to build this is recorded in the `.nvmrc` file). Then, in a terminal opened in this folder:

1. `npm install` downloads what the site needs. You only do this once, or after the list of tools changes.
2. `npm run dev` starts a local copy you can look at in your browser. The terminal prints the address. Press Ctrl+C to stop it.
3. `npm run build` produces the finished site in a folder called `dist`.

## What is in each folder

- `site.config.mjs`: the one file holding the site name, publisher, authorisation line, contact email, footer text and web address. Change the name or owner here and nowhere else.
- `src/`: the pages, the shared page layout and the styling.
- `metrics/`: one folder per metric, with its data and checking notes. Empty for now. See `metrics/README.md`.
- `shared/`: lists used on every chart: `governments.csv` (when each government was sworn in) and `events.csv` (the marked events).
- `scrapers/`: the Python programs that will download official data. None yet. See `scrapers/README.md`.
- `public/`: files copied to the site as they are.
- `dist/`: the built site. Created by `npm run build`. Not kept in version history.

## How changes arrive

Changes are sent as patch files. Only the owner applies them. Nothing changes the project by any other route.
