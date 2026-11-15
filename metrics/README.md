# Metrics

Each metric has its own folder here. The folder name is the metric's short name (the "slug"), for example `commonwealth-debt`. There are no metrics yet.

## Layout of one metric folder

```
metrics/<slug>/
  metric.yml   what the metric is: title, theme, series, sources, target, tests it passed
  data.csv     the numbers, in the shape described below
  sources/     the raw files exactly as downloaded from the official source
  NOTES.md     the checking record, including who checked the figures and when
```

A folder only counts as a metric once it contains `metric.yml`.

## The data.csv columns

The file is in "long" format: one row per date, series and jurisdiction.

| Column | What it holds |
|---|---|
| `date` | A real date, such as 2025-06-30. Never a label like "2024-25". |
| `series` | The series id from `metric.yml`, such as `gross_debt`. |
| `jurisdiction` | Who the figure covers, such as `Commonwealth`, or a state or territory. |
| `value` | The number, as published or computed in code. |
| `unit` | What the number is measured in, such as `$ million` or `% of GDP`. |
| `status` | One of `actual`, `estimate` or `forecast`. |
| `period` | The source's own period label, such as `2024-25`, kept for reference. |

Every number must come from a file in `sources/`. Nothing is typed in by hand.
