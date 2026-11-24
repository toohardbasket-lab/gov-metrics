# Metrics

Each metric has its own folder here. The folder name is the metric's short name (the "slug"), for example `commonwealth-debt`. The metrics so far are `commonwealth-debt`, built from figures parsed by code from Treasury's Word files, `unemployment-rate`, read by code from the ABS Data API and checked against the ABS Labour Force spreadsheet, `inflation`, three series (quarterly and monthly) checked against second sources, `wages-and-prices`, the ABS Wage Price Index beside the inflation page's quarterly figures, and `rents`, the ABS rents index with a worked-out quarterly change, the monthly figure and a capital city panel (see `scrapers/README.md`). Each is a draft until its owner has checked it.

Every folder that contains a `metric.yml` gets a page at `/metrics/<slug>/` and a link on the home page. The page is drawn entirely from the files in the folder, plus the shared lists in `shared/`. Nothing about any one metric is written into the site code.

## Layout of one metric folder

```
metrics/<slug>/
  metric.yml   what the metric is and everything the page says about it (see below)
  data.csv     the numbers, in the shape described below
  sources/     the raw files exactly as downloaded from the official source
  NOTES.md     the checking record, including who checked the figures and when
```

A folder only counts as a metric once it contains `metric.yml`.

## The data.csv columns

The file is in "long" format: one row per date, series and jurisdiction. The header is exactly:

`date,period,series,jurisdiction,value,unit,status`

| Column | What it holds |
|---|---|
| `date` | A real date, such as 2025-06-30. Never a label like "2024-25". |
| `period` | The source's own period label, such as `2024-25`, kept for reference and shown in the table. |
| `series` | The series id from `metric.yml`, such as `gross_debt`. |
| `jurisdiction` | Who the figure covers, such as `Commonwealth`, or a state or territory. |
| `value` | The number, as published or computed in code. |
| `unit` | What the number is measured in. The page knows `aud_million` (dollars, in millions), `pct_gdp` (per cent of GDP), `pct` (per cent, such as a rate; shown as 4.9%) and `index` (an index number with one or two decimals, no % sign; shown as 103.3 or 7.07). A new unit needs a line in `src/lib/format.ts`. |
| `status` | One of `actual`, `estimate` or `forecast`. |

Every number must come from a file in `sources/`. Nothing is typed in by hand. The files must not contain quote marks or commas inside values; the page builder stops with an error if it finds a quote mark.

## The metric.yml fields

All text on the page comes from here. Plain text only, no HTML. Two small extras are allowed in text: `**bold**`, and words in braces that are filled in when the page is built. In the two ledgers `{link}`, `{update}` and `{retrieved}` come from the row's `link` and the `update` and `retrieved` fields. Everywhere (lede, view labels and captions, table headings, the chart description and source line, and every ledger and list) these come from the data:

| Word | Filled in with |
|---|---|
| `{real_base}` | The latest June in the data, as month and year, such as June 2026. This is the price base of the inflation-adjusted views. |
| `{real_base_index}` | The price index for that June, exactly as printed in `shared/cpi_june.csv`. |
| `{first_real_year}` | The first year that has a price index figure, so the first year of the inflation-adjusted views. |
| `{first_year}`, `{last_year}` | The calendar years of the earliest and latest dates in `data.csv`. |
| `{latest_period}` | The period label of the latest row, such as 2025-26. When several series end on the same date, set `latest_period_series` in `metric.yml` to the series whose latest period it should name (the inflation page uses the monthly series). |

An unknown word, or one that cannot be worked out, stops the build. Do not type a year or an index value into the text when one of these will do.

| Field | What it does |
|---|---|
| `slug`, `title`, `theme`, `jurisdiction` | Identity, and the label above the title. `slug` must match the folder name. |
| `description` | Short summary used in the page's meta description. |
| `lede` | The one-sentence description under the title. |
| `draft`, `draft_banner` | If `draft` is true, the banner text is shown at the top and the home page adds "(draft)". |
| `series` | Each series id, its label, definition and source table. |
| `tiles` | The boxes above the chart. A tile with a `series` shows that series' latest value, with a `sub` series (and `suffix`) beneath. A tile with `text` and `sub_text` shows fixed words, such as the target status. A tile with a `series` may also have `sub_month: true` (the label stays plain and the month and year, such as October 2026, go beneath the figure) or `sub_quarter: true` (the same, but the quarter, such as September quarter 2026) and `months_back: 12` (the figure for the same month that many months before the latest, so 12 is a year earlier; it cannot be combined with `sub`). |
| `views` | The chart's view buttons, in order. Each has an `id`, a `label`, a `caption`, and one to three `lines` (a series id and a label, and optionally `color: 1`, `2` or `3`, the series colour, which defaults to the line's position; set it so a series keeps its colour in every view). Each line may also name a `jurisdiction` (see below). `derive: none` plots data.csv as it is. `derive: real` multiplies each value by the CPI of the latest June in the data divided by the CPI of that row's June, using `shared/cpi_june.csv`. Rows with no CPI figure are left out of that view. All lines in a view share one unit. Each line draws its own points, so a quarterly and a monthly series can share a chart; the hover read-out shows each line's value at its own nearest date, and "no figure" for a line with nothing near the cursor. Two optional settings per view: `from: 1983` starts the view in that year (the data before it is not drawn, and the axis starts there), and `target_band: {min: 2, max: 3, label: "Target band 2–3%"}` shades a band across the plot (pale blue with dashed edges, not a status colour) with its label and a legend entry. |
| `chart_alt`, `chart_source` | The chart's text description for screen readers, and the source line after each caption. |
| `table` | The column headings of the full table and which series (and whether `derive: real`, and which `jurisdiction`) each column shows. Optional: `period_format: month_year` shows each row's date as "September 2026" instead of the period label (use it when the series have different frequencies; there is one row for each date that has a figure in any series), and `missing: ""` sets what a cell with no figure shows (the default is n/a). |
| `meaning` | The "What the numbers mean" paragraphs. |
| `targets` | Rows of the "Targets and forecasts" ledger. |
| `sources_method`, `update`, `retrieved` | Rows of the "Sources and method" ledger, how often the data is updated, and the date it was retrieved. |
| `read_with_care` | The "Read with care" list. |
| `corrections_text` | The text of the page's Corrections section. |
| `targets` (with dates) | The same `targets` list may also hold entries with a `label` and a `due` date (YYYY-MM-DD). The weekly report lists any that are due within 90 days or overdue. An entry with a `due` date still needs its `text`, because the page draws every entry in the list. Entries without `due`, like the ones now in the debt metric, are ignored by the report. Write each one with its keys on separate lines (or as one `{label: ..., due: ...}` line), because the report reads this list without a YAML library. |
| `state_panel`, `state_panel_config` | `state_panel: true` draws the state and territory panel under the targets (see below). `false` draws nothing. |
| `real_method`, `target`, `legal_limit`, `inclusion_tests` | Notes kept in the definition file. Not drawn on the page yet. |

### Jurisdictions in views, tiles and tables

A series may have rows for more than one jurisdiction (for example `rents_monthly` for Australia and for each state and territory). Wherever such a series is used (a view line, a tile, a tile's `sub`, a table column) it must say which one with `jurisdiction: Australia`. A series with one jurisdiction needs nothing. The checker stops the build if a series with several jurisdictions is used without one, or if the jurisdiction named has no figures. Use the full state or territory name in data.csv (New South Wales, Victoria, Queensland, Western Australia, South Australia, Tasmania, Australian Capital Territory, Northern Territory).

### Derived series

A series that is worked out from a stored series is declared in `series` with a `derive` setting and is not in data.csv:

```yaml
- id: rents_quarterly
  label: Rents, quarterly (worked out)
  derive: {type: year_ended_change, from: rents_index_quarterly, lag: 4}
  frequency: quarterly
  plausible: {min: -20, max: 40}
```

`year_ended_change` is (value this period ÷ value `lag` periods earlier − 1) × 100, rounded half up to one decimal place (a tie goes away from zero, as the scrapers round). The sums are exact (whole numbers, no floating point) on the figures as written in data.csv. A period with no figure `lag` periods earlier (the start of the series, or a gap) has no derived figure: it is left out, never worked out from a different period. The same code (`src/lib/derive.mjs`) is used by the checker and the page, so they cannot disagree. A derived series is used in views, tiles and table columns like any other (its unit is `pct`), needs `frequency` (the same as the series it comes from, monthly or quarterly) and `plausible` (checked on the worked-out figures), needs no `revision` (nothing is stored to revise; the stored series carries it) and must not have rows in data.csv. Print the formula on the page, in "Sources and method".

### The state and territory panel

`state_panel: true` needs a `state_panel_config` (plan section 3):

```yaml
state_panel: true
state_panel_config:
  series: rents_monthly          # a stored series with one row set per jurisdiction
  national: Australia            # drawn as the thin grey line on every small chart
  national_label: Eight capital cities
  heading: Capital cities
  note: "..."                    # the words under the heading
  headers: [Capital city, Month, Rents over twelve months]   # the three column headings of the table
  places:                        # the eight, in this fixed order
    - {jurisdiction: New South Wales, abbreviation: NSW, name: Sydney}
    ...
```

The panel shows eight small charts in the fixed order NSW, Vic, Qld, WA, SA, Tas, ACT, NT, each labelled "name (abbreviation)", all on one y-axis scale (fitted to every place and the national line), no ranking colours, with the same government shading as the main chart, and under them a table of the latest figure for each place in the same order (not sorted by value). The checker refuses any other order or abbreviation, a place with no rows, and places that end in different months.

### Fields the checker needs on each series

Each entry in `series` must also carry these, or `npm run validate` fails and the build stops:

| Field | What it does |
|---|---|
| `frequency` | How often the series has a point: `annual`, `quarterly` or `monthly`. For `annual`, consecutive points must be exactly one year apart on the same month and day, so a missing year is caught. For `monthly`, every date must be the last day of a month (28 or 29 February, 30 April and so on) and consecutive points must be in consecutive months, so a missing month is caught. For `quarterly`, every date must be the last day of March, June, September or December (31 March, 30 June, 30 September, 31 December) and consecutive points must be consecutive quarters, so a missing quarter is caught. An unknown word fails with a clear message. |
| `plausible` | The range a real value must fall inside, for example `{min: 0, max: 100}`. A value outside it stops the build. Choose it wide enough that real data never touches it, and narrow enough that a slipped decimal point or a flipped sign does. |
| `max_step_pct` (optional) | The largest allowed change between consecutive points, as a per cent of the earlier point. Left out for the debt series. |
| `revision` | How far an already accepted figure may change before the checker blocks it. Required on every series. See "Revision tolerance" below. |
| `copy_of` (optional) | Written on one line as `copy_of: {metric: inflation, series: headline_quarterly}`. It says this series is a copy of a series on another metric's page. The checker then requires every row of this series to have a row in that metric's `data.csv` with the same date, jurisdiction, value and unit, and stops the build with a message naming the row if one differs, is missing, or the other metric or series cannot be found. The scraper that writes the copy records the other file's path and checksum in this metric's `sources/manifest.json` as an entry with a `path` (instead of a downloaded file); the checker checks only the shape of such an entry, because the other file may change later. |
| `max_step_floor` (optional) | With `max_step_pct`, the step limit only applies where the earlier point's size (ignoring its sign) is at least this. It stops a series that passes through zero from failing. Default 0. |

The checker also needs these top-level fields in `metric.yml`: `slug`, `title`, `theme`, `jurisdiction`, `lede`, `draft`, `series`, `tiles`, `views`, `chart_alt`, `chart_source`, `table`, `meaning`, `targets`, `sources_method`, `read_with_care`, `corrections_text`, `update` and `retrieved`. A series must be declared in `series` if it is in `data.csv`, and every series used in a view, tile or table column must have data.

### Revision tolerance

Every series needs a `revision` setting, written on one line, for example `revision: {max_abs: 1}` (any change of more than 1 blocks) or `revision: {max_abs: 500, max_pct: 1, pct_floor: 5000}` (a change blocks only if it is more than 500 and more than 1 per cent). It is the allowed change to a figure that has already been accepted (a date that is in both `data.lock.json` and `data.csv`). New dates are never revisions.

| Field | What it does |
|---|---|
| `max_abs` | Required. The largest allowed change, in the series' own units (millions of dollars, or percentage points of GDP). |
| `max_pct` (optional) | The largest allowed change as a per cent of the old figure's size (ignoring its sign). With it, a change fails only if it is over both `max_abs` and `max_pct`. |
| `pct_floor` (optional) | `max_pct` only applies where the old figure's size is at least this. Below it, only `max_abs` applies. |

A change over the tolerance stops the build (and `npm run accept-data`) until it is accepted with `npm run accept-data -- --accept-revisions`. A change within it gives only a warning. Also, a change of sign fails whatever its size, if both the old and the new figures are at least `pct_floor` in size (or at least `max_abs` when there is no `pct_floor`). Write the setting on one line: the weekly report (`scrapers/report.py`) has no YAML library and reads only that form to mark large revisions. Keep a comment beside the setting saying why the numbers were chosen.

### The lock file

`metrics/<slug>/data.lock.json` is written by `npm run accept-data`. It records, for each series, the number of rows, the first date and the last date, every accepted value (as written in `data.csv`), and a fingerprint of `data.csv`, plus a `lock_version` number (now 2). A lock file without it is in the old format: the checker fails and `npm run accept-data` upgrades it. The file is kept in version history with the data. See the main `README.md` for when to run the command.

## Shared files used by every chart

`shared/governments.csv` (shaded bands), `shared/events.csv` (event marks) and `shared/cpi_june.csv` (June quarter price index for the real-terms views, written by `scrapers/cpi_june.py`). Dates in the first two decide where the marks go.
