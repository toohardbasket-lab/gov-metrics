# Metrics

Each metric has its own folder here. The folder name is the metric's short name (the "slug"), for example `commonwealth-debt`. The only metric so far is `commonwealth-debt`, built from prototype data.

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
| `unit` | What the number is measured in. The page knows `aud_million` (dollars, in millions) and `pct_gdp` (per cent of GDP). A new unit needs a line in `src/lib/format.ts`. |
| `status` | One of `actual`, `estimate` or `forecast`. |

Every number must come from a file in `sources/`. Nothing is typed in by hand. The files must not contain quote marks or commas inside values; the page builder stops with an error if it finds a quote mark.

## The metric.yml fields

All text on the page comes from here. Plain text only, no HTML. Two small extras are allowed in text: `**bold**`, and in the two ledgers `{link}`, `{update}` and `{retrieved}`, which are filled in from the row's `link` and the `update` and `retrieved` fields.

| Field | What it does |
|---|---|
| `slug`, `title`, `theme`, `jurisdiction` | Identity, and the label above the title. `slug` must match the folder name. |
| `description` | Short summary used in the page's meta description. |
| `lede` | The one-sentence description under the title. |
| `draft`, `draft_banner` | If `draft` is true, the banner text is shown at the top and the home page adds "(draft)". |
| `series` | Each series id, its label, definition and source table. |
| `tiles` | The boxes above the chart. A tile with a `series` shows that series' latest value, with a `sub` series (and `suffix`) beneath. A tile with `text` and `sub_text` shows fixed words, such as the target status. |
| `views` | The chart's view buttons, in order. Each has an `id`, a `label`, a `caption`, and one or two `lines` (a series id and a label). `derive: none` plots data.csv as it is. `derive: real` multiplies each value by the CPI of the latest June in the data divided by the CPI of that row's June, using `shared/cpi_june.csv`. Rows with no CPI figure are left out of that view. All lines in a view share one unit. |
| `chart_alt`, `chart_source` | The chart's text description for screen readers, and the source line after each caption. |
| `table` | The column headings of the full table and which series (and whether `derive: real`) each column shows. |
| `meaning` | The "What the numbers mean" paragraphs. |
| `targets` | Rows of the "Targets and forecasts" ledger. |
| `sources_method`, `update`, `retrieved` | Rows of the "Sources and method" ledger, how often the data is updated, and the date it was retrieved. |
| `read_with_care` | The "Read with care" list. |
| `corrections_text` | The text of the page's Corrections section. |
| `real_method`, `target`, `legal_limit`, `state_panel`, `inclusion_tests` | Notes kept in the definition file. Not drawn on the page yet. |

## Shared files used by every chart

`shared/governments.csv` (shaded bands), `shared/events.csv` (event marks) and `shared/cpi_june.csv` (June quarter price index for the real-terms views). Dates in the first two decide where the marks go.
