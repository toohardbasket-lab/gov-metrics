import { readdirSync, statSync, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parse as parseYaml } from 'yaml';
import { parseCsv } from './csv';
import { formatDate, formatMonthYear, formatQuarterYear, formatTable, formatValue } from './format';
import { escapeHtml, fillPlain, richText } from './text';
import { computeDerived, isValueCode } from './derive.mjs';
import { STATE_ORDER } from './jurisdictions.mjs';
import { STATUS_WORDS } from './status.mjs';

const ROOT = process.cwd();
// The most lines one view can draw: the page defines this many series colours (--series-1 to --series-5).
const MAX_LINES = 5;

// Lists metric folders (metrics/<slug>/ that contain a metric.yml) at build time.
export function listMetricSlugs(): string[] {
  const root = join(ROOT, 'metrics');
  if (!existsSync(root)) return [];
  return readdirSync(root)
    .filter((name) => statSync(join(root, name)).isDirectory())
    .filter((name) => existsSync(join(root, name, 'metric.yml')))
    .sort();
}

// ---- what metric.yml holds (see metrics/README.md) ----
interface LedgerRow {
  label: string;
  text: string;
  link?: { label: string; url: string };
}
interface TableDef { period_header: string; period_format?: 'period' | 'month_year'; missing?: string; columns: { header: string; series: string; jurisdiction?: string; derive?: 'real' }[] }
export interface MetricDef {
  slug: string;
  title: string;
  theme: string;
  jurisdiction: string;
  description?: string;
  lede: string;
  latest_period_series?: string;
  draft?: boolean;
  draft_banner?: string;
  series: { id: string; label: string; frequency?: string; decimals?: number; derive?: { type: string; from?: string | string[]; lag?: number; start?: string | { date: string; value: number }; end?: { date: string; value: number }; jurisdiction?: string; numerator?: string; denominator?: string; denominator_date?: string; factor?: number; decimals?: number; unit?: string } }[];
  // The official status of the target, in a form a future Targets page can read (plan section 4). `status` is one of STATUS_WORDS.
  status?: { status: string; assessed_by: string; assessed_on: string; due: string };
  state_panel?: boolean;
  state_panel_config?: {
    series: string;
    national: string;
    national_label: string;
    heading: string;
    note: string;
    headers: string[];
    date_format?: 'period' | 'month_year';
    extra_columns?: { header: string; series: string; after?: boolean; own_latest?: boolean; with_period?: boolean }[];
    markers?: boolean;
    y_range?: { min: number; max: number };
    places: { jurisdiction: string; abbreviation: string; name: string }[];
  };
  tiles: {
    label: string;
    series?: string;
    jurisdiction?: string;
    sub?: { series: string; suffix: string; jurisdiction?: string };
    months_back?: number;
    sub_month?: boolean;
    sub_quarter?: boolean;
    sub_date?: boolean;
    sub_period?: boolean;
    sub_prefix?: string;
    text?: string;
    from_status?: boolean; // the tile shows the status word from the metric's `status` block
    sub_text?: string;
  }[];
  views: {
    id: string;
    label: string;
    derive: 'none' | 'real';
    lines: { series: string; jurisdiction?: string; label: string; color?: number; dash?: boolean }[];
    from?: number;
    to?: string;
    markers?: boolean;
    target_band?: { min: number; max: number; label: string };
    reference_lines?: { value: number; label: string; style: 'solid' | 'dashed' }[];
    caption: string;
  }[];
  chart_alt: string;
  chart_source: string;
  table: TableDef | TableDef[];
  meaning: string[];
  targets: LedgerRow[];
  update: string;
  retrieved: string;
  sources_method: LedgerRow[];
  read_with_care: string[];
  corrections_text: string;
}

// ---- what the page needs, ready to draw ----
interface DataRow {
  date: string;
  period: string;
  series: string;
  jurisdiction: string;
  value: number;
  valueText: string; // as written in data.csv (derived figures are worked out from this text)
  isCode?: boolean; // the value is a source code (.., na, np, -), not a number: value is NaN
  unit: string;
  status: string;
}

// Each line carries its own points, so lines of different frequencies can share one chart.
// `color` is 1 to 5 (the --series-N colours). `from` is the first year drawn, when the view starts
// later than the data. `band` is a shaded band across the plot (for example a target range).
export interface ChartLine {
  label: string;
  color: number;
  dash?: boolean; // draw this line dashed
  decimals?: number; // decimal places to show for this line's figures (the series' `decimals`), if it sets any
  points: { date: string; period: string; value: number }[];
}
export interface ChartView {
  id: string;
  label: string;
  caption: string;
  unit: string;
  from?: number;
  to?: string; // the last date the axis shows (the date of the last point drawn is at most this)
  markers?: boolean; // draw a marker on every point
  band?: { min: number; max: number; label: string };
  referenceLines?: { value: number; label: string; style: 'solid' | 'dashed' }[]; // horizontal lines at a value (solid: the current target, dashed: a superseded one)
  lines: ChartLine[];
}
export interface ChartData {
  alt: string;
  source: string;
  views: ChartView[];
  governments: { date: string; party: string }[];
  events: { date: string; label: string }[];
}
// The state and territory panel (plan section 3): small charts in a fixed order on one shared scale.
export interface PanelPlace {
  label: string; // "Sydney (NSW)"
  name: string;
  abbreviation: string;
  points: { date: string; period: string; value: number }[];
}
export interface PanelData {
  heading: string;
  note: string;
  frequency: string;
  unit: string;
  decimals?: number;
  yRange?: { min: number; max: number };
  markers?: boolean; // draw a marker on every point of every small chart
  nationalLabel: string;
  national: { date: string; period: string; value: number }[];
  places: PanelPlace[];
  figureHeader: string; // the heading of the figure column (the charts' description uses it)
  table: { headers: string[]; rows: { place: string; month: string; extras: string[]; extrasAfter: string[]; value: string }[] };
  governments: { date: string; party: string }[];
  events: { date: string; label: string }[];
}
export interface Metric {
  def: MetricDef;
  panel?: PanelData;
  tiles: { key: string; value: string; sub: string; isText: boolean }[];
  chart: ChartData;
  tables: { headers: string[]; periodHeader: string; rows: { period: string; cells: string[] }[] }[];
  rich: {
    banner: string;
    meaning: string[];
    targets: { label: string; html: string }[];
    sourcesMethod: { label: string; html: string }[];
    care: string[];
    corrections: string;
  };
}

function need(cond: unknown, slug: string, msg: string): asserts cond {
  if (!cond) throw new Error(`metrics/${slug}/metric.yml: ${msg}`);
}

function readCsv(path: string): Record<string, string>[] {
  return parseCsv(readFileSync(path, 'utf8'), path);
}

function loadData(slug: string): DataRow[] {
  const rows = readCsv(join(ROOT, 'metrics', slug, 'data.csv')).map((r) => {
    const isCode = isValueCode(r.value);
    const value = isCode ? NaN : Number(r.value);
    if (!isCode && (r.value === '' || Number.isNaN(value))) throw new Error(`metrics/${slug}/data.csv: bad value "${r.value}" for ${r.series} ${r.date}`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(r.date)) throw new Error(`metrics/${slug}/data.csv: bad date "${r.date}"`);
    return { date: r.date, period: r.period, series: r.series, jurisdiction: r.jurisdiction, value, valueText: r.value, isCode, unit: r.unit, status: r.status };
  });
  const seen = new Set<string>();
  for (const r of rows) {
    const k = `${r.series}|${r.date}|${r.jurisdiction}`;
    if (seen.has(k)) throw new Error(`metrics/${slug}/data.csv: duplicate row ${k}`);
    seen.add(k);
  }
  return rows;
}

// The index as a number for the sums, and as printed in the file for the page text.
function loadCpi(): { values: Map<string, number>; printed: Map<string, string> } {
  const values = new Map<string, number>();
  const printed = new Map<string, string>();
  for (const r of readCsv(join(ROOT, 'shared', 'cpi_june.csv'))) {
    values.set(r.date, Number(r.index));
    printed.set(r.date, r.index);
  }
  return { values, printed };
}

export function loadMetric(slug: string): Metric {
  const def = parseYaml(readFileSync(join(ROOT, 'metrics', slug, 'metric.yml'), 'utf8')) as MetricDef;
  for (const k of ['title', 'theme', 'jurisdiction', 'lede', 'series', 'tiles', 'views', 'chart_alt', 'chart_source', 'table', 'meaning', 'targets', 'sources_method', 'read_with_care', 'corrections_text', 'retrieved', 'update']) {
    need((def as any)[k] !== undefined, slug, `missing "${k}"`);
  }
  need(def.slug === slug, slug, `slug "${def.slug}" does not match the folder name`);
  if (def.draft) need(def.draft_banner, slug, 'draft is true but draft_banner is missing');

  const data = loadData(slug);
  // Every series, stored or derived, by "series|jurisdiction" -> date -> row. A series with figures for
  // more than one jurisdiction must be picked with `jurisdiction:` wherever it is used.
  const store = new Map<string, Map<string, DataRow>>();
  const jurisdictionsOf = new Map<string, string[]>();
  const addRow = (r: DataRow) => {
    const key = `${r.series}|${r.jurisdiction}`;
    if (!store.has(key)) store.set(key, new Map());
    store.get(key)!.set(r.date, r);
    const js = jurisdictionsOf.get(r.series) ?? [];
    if (!js.includes(r.jurisdiction)) js.push(r.jurisdiction);
    jurisdictionsOf.set(r.series, js);
  };
  for (const r of data) addRow(r);
  // Derived series (metric.yml `derive`) are worked out here with the same code as the checker
  // (src/lib/derive.mjs). A date where an input is missing, unknown or a code has no derived figure.
  const storedForDerive = new Map<string, { date: string; period: string; valueText: string; unit: string }[]>();
  for (const r of data) {
    const k = `${r.series}|${r.jurisdiction}`;
    if (!storedForDerive.has(k)) storedForDerive.set(k, []);
    storedForDerive.get(k)!.push({ date: r.date, period: r.period, valueText: r.valueText, unit: r.unit });
  }
  const worked = computeDerived(def.series, storedForDerive);
  need(worked.problems.length === 0, slug, worked.problems.join(' '));
  for (const [key, rows] of worked.groups) {
    const sid = key.split('|')[0];
    for (const d of rows) addRow({ date: d.date, period: d.period, series: sid, jurisdiction: key.slice(sid.length + 1), value: d.value, valueText: d.valueText, unit: d.unit, status: 'actual' });
  }
  const rowsOf = (id: string, jurisdiction: string | undefined, where: string) => {
    const js = jurisdictionsOf.get(id) ?? [];
    need(js.length > 0, slug, `${where} uses series "${id}" which has no rows in data.csv`);
    let j = jurisdiction;
    if (j === undefined) {
      need(js.length === 1, slug, `${where} uses series "${id}", which has figures for several jurisdictions (${js.join(', ')}); name one with jurisdiction`);
      j = js[0];
    }
    const m = store.get(`${id}|${j}`);
    need(m && m.size > 0, slug, `${where} uses series "${id}" in the jurisdiction "${j}", which has no rows`);
    return m;
  };
  const unitOf = (id: string, jurisdiction: string | undefined, where: string) => {
    const units = new Set([...rowsOf(id, jurisdiction, where).values()].map((r) => r.unit));
    need(units.size === 1, slug, `series "${id}" has more than one unit`);
    return [...units][0];
  };
  // `decimals` on a series is a display setting: the places shown for its per cent or rate figures.
  const decimalsOf = (id: string): number | undefined => def.series.find((x) => x.id === id)?.decimals;
  for (const s of def.series) need(jurisdictionsOf.has(s.id), slug, `series "${s.id}" is listed but has no rows in data.csv`);

  const { values: cpi, printed: cpiPrinted } = loadCpi();

  // Words the metric.yml text may use, filled in from the data (see metrics/README.md).
  // A token whose value cannot be worked out is left out, so using it stops the build.
  const dataDates = [...new Set(data.map((r) => r.date))].sort();
  const juneDates = dataDates.filter((d) => d.slice(5, 7) === '06');
  const textTokens: Record<string, string> = {
    first_year: dataDates[0].slice(0, 4),
    last_year: dataDates.at(-1)!.slice(0, 4),
    latest_period: data.find((r) => r.date === dataDates.at(-1))!.period,
    // The source's own label for the earliest period, e.g. "2015-16" for a financial year.
    first_period: data.find((r) => r.date === dataDates[0])!.period,
  };
  // {first_period:<series id>} is the period label of that series' earliest row, for text about one series
  // when the metric's series start in different years (for example {first_period:clients}).
  const firstOfSeries = new Map<string, DataRow>();
  for (const [key, m] of store) {
    const id = key.slice(0, key.indexOf('|'));
    for (const r of m.values()) if (!firstOfSeries.has(id) || r.date < firstOfSeries.get(id)!.date) firstOfSeries.set(id, r);
  }
  for (const [id, r] of firstOfSeries) textTokens[`first_period:${id}`] = r.period;
  // With several series ending on the same date the first row found is not meaningful, so a metric
  // can say which series {latest_period} names (the period of that series' latest row).
  if (def.latest_period_series !== undefined) {
    const own = data.filter((r) => r.series === def.latest_period_series);
    need(own.length > 0, slug, `latest_period_series "${def.latest_period_series}" has no rows in data.csv`);
    textTokens.latest_period = own.reduce((a, b) => (b.date > a.date ? b : a)).period;
  }
  if (juneDates.length > 0) {
    const latestJune = juneDates.at(-1)!;
    textTokens.real_base = formatMonthYear(latestJune);
    if (cpiPrinted.has(latestJune)) textTokens.real_base_index = cpiPrinted.get(latestJune)!;
    const withCpi = juneDates.filter((d) => cpi.has(`${d.slice(0, 4)}-06-30`));
    if (withCpi.length > 0) textTokens.first_real_year = withCpi[0].slice(0, 4);
  }
  const fill = (text: string) => fillPlain(text, textTokens);
  def.lede = fill(def.lede);
  if (def.description) def.description = fill(def.description);
  // Real value = nominal x (CPI of the latest June in the data / CPI of that row's June).
  // The CPI is looked up by the 30 June of the row's year (shared/cpi_june.csv).
  const realValue = (row: DataRow, latestJune: string): number | undefined => {
    const idx = cpi.get(`${row.date.slice(0, 4)}-06-30`);
    const latestIdx = cpi.get(latestJune);
    need(latestIdx !== undefined, slug, `no CPI index in shared/cpi_june.csv for ${latestJune}`);
    if (idx === undefined) return undefined;
    return Math.round(row.value * (latestIdx / idx));
  };
  type Pick = { series: string; jurisdiction?: string };
  const latestJuneFor = (picks: Pick[]) => {
    const dates = picks.flatMap((p) => [...rowsOf(p.series, p.jurisdiction, 'a view').keys()]).filter((d) => d.slice(5, 7) === '06');
    need(dates.length > 0, slug, 'a real-terms view needs data dated in June');
    return dates.sort().at(-1)!;
  };
  const valueFor = (id: string, jurisdiction: string | undefined, date: string, derive?: string, latestJune?: string): number | undefined => {
    const row = rowsOf(id, jurisdiction, 'a figure').get(date);
    if (!row || row.isCode) return undefined; // a code (.., na, np, -) is a date with no figure
    return derive === 'real' ? realValue(row, latestJune!) : row.value;
  };

  // Chart views. Each line uses its own points (a series with no figure on a date has no point
  // there), so quarterly and monthly lines can share a chart.
  const views: ChartView[] = def.views.map((v) => {
    need(v.lines.length >= 1 && v.lines.length <= MAX_LINES, slug, `view "${v.id}" must have one to ${MAX_LINES} lines (the page defines ${MAX_LINES} series colours)`);
    const units = new Set(v.lines.map((l) => unitOf(l.series, l.jurisdiction, `view "${v.id}"`)));
    need(units.size === 1, slug, `view "${v.id}" mixes units; one scale per view`);
    const latestJune = v.derive === 'real' ? latestJuneFor(v.lines) : undefined;
    if (v.from !== undefined) need(Number.isInteger(v.from) && v.from > 1000 && v.from < 3000, slug, `view "${v.id}" has a "from" that is not a year`);
    if (v.to !== undefined) need(typeof v.to === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v.to), slug, `view "${v.id}" has a "to" that is not a date written YYYY-MM-DD`);
    const refs = v.reference_lines;
    if (refs !== undefined) {
      need(Array.isArray(refs) && refs.length > 0, slug, `view "${v.id}" has a reference_lines that is not a list`);
      for (const r of refs) {
        need(typeof r?.value === 'number' && Number.isFinite(r.value), slug, `view "${v.id}" has a reference line whose value is not a number`);
        need(typeof r.label === 'string' && r.label.trim() !== '', slug, `view "${v.id}" has a reference line with no label`);
        need(r.style === 'solid' || r.style === 'dashed', slug, `view "${v.id}" has a reference line whose style is not solid or dashed`);
      }
    }
    const b = v.target_band;
    if (b !== undefined) {
      need(typeof b.min === 'number' && typeof b.max === 'number' && b.min < b.max, slug, `view "${v.id}" has a target_band whose min and max are not numbers with min below max`);
      need(typeof b.label === 'string' && b.label.trim() !== '', slug, `view "${v.id}" has a target_band with no label`);
    }
    const firstDate = v.from !== undefined ? `${v.from}-01-01` : '0000-01-01';
    const lastDate = v.to !== undefined ? v.to : '9999-12-31';
    const lines: ChartLine[] = v.lines.map((l, i) => {
      const color = l.color ?? i + 1;
      need(Number.isInteger(color) && color >= 1 && color <= MAX_LINES, slug, `view "${v.id}" has a line colour that is not a whole number from 1 to ${MAX_LINES}`);
      const points: ChartLine['points'] = [];
      const own = rowsOf(l.series, l.jurisdiction, `view "${v.id}"`);
      for (const date of [...own.keys()].sort()) {
        if (date < firstDate || date > lastDate) continue;
        const value = valueFor(l.series, l.jurisdiction, date, v.derive, latestJune);
        if (value === undefined) continue;
        points.push({ date, period: own.get(date)!.period, value });
      }
      need(points.length > 0, slug, `view "${v.id}" has no points for series "${l.series}"${v.from !== undefined ? ` from ${v.from}` : ''}`);
      const decimals = decimalsOf(l.series);
      need(l.dash === undefined || typeof l.dash === 'boolean', slug, `view "${v.id}" has a line whose dash is not true or false`);
      return { label: l.label, color, ...(l.dash === true ? { dash: true } : {}), ...(decimals !== undefined ? { decimals } : {}), points };
    });
    return {
      id: v.id, label: fill(v.label), caption: fill(v.caption), unit: [...units][0],
      ...(v.from !== undefined ? { from: v.from } : {}),
      ...(v.to !== undefined ? { to: v.to } : {}),
      ...(v.markers === true ? { markers: true } : {}),
      ...(refs !== undefined ? { referenceLines: refs.map((r) => ({ value: r.value, label: fill(r.label), style: r.style })) } : {}),
      ...(b !== undefined ? { band: { min: b.min, max: b.max, label: b.label } } : {}),
      lines,
    };
  });

  const governments = readCsv(join(ROOT, 'shared', 'governments.csv'))
    .map((r) => ({ date: r.sworn_in, party: r.party }))
    .sort((a, b) => a.date.localeCompare(b.date));
  const events = readCsv(join(ROOT, 'shared', 'events.csv'))
    .map((r) => ({ date: r.date, label: r.label }))
    .sort((a, b) => a.date.localeCompare(b.date));

  // Tiles: the latest value of each series.
  const latestOf = (id: string, jurisdiction: string | undefined, where: string) => {
    const m = rowsOf(id, jurisdiction, where);
    const date = [...m.values()].filter((r) => !r.isCode).map((r) => r.date).sort().at(-1);
    need(date, slug, `${where} uses series "${id}", which has no figure (only codes)`);
    return m.get(date!)!;
  };
  // A tile with months_back shows the figure for the same calendar month that many months before
  // the latest (12 = a year earlier). A tile with sub_month puts the month and year beneath the
  // figure and leaves the label plain; without it the full date goes after the label.
  const monthsBefore = (iso: string, n: number) => {
    const total = +iso.slice(0, 4) * 12 + (+iso.slice(5, 7) - 1) - n;
    return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, '0')}`;
  };
  const tiles = def.tiles.map((t) => {
    if (t.series) {
      let r = latestOf(t.series, t.jurisdiction, 'a tile');
      if (t.months_back !== undefined) {
        need(Number.isInteger(t.months_back) && t.months_back > 0, slug, `tile "${t.label}" has a months_back that is not a whole number above zero`);
        const want = monthsBefore(r.date, t.months_back);
        const found = [...rowsOf(t.series, t.jurisdiction, 'a tile').values()].find((x) => x.date.slice(0, 7) === want);
        need(found, slug, `tile "${t.label}" needs a figure for ${want}, ${t.months_back} months before ${r.date}, but data.csv has none`);
        r = found!;
      }
      need(!(t.sub && t.months_back !== undefined), slug, `tile "${t.label}" cannot have both sub and months_back`);
      let sub = '';
      if (t.sub) {
        const s = latestOf(t.sub.series, t.sub.jurisdiction, 'a tile');
        need(s.date === r.date, slug, `tile "${t.label}" and its sub series have different latest dates`);
        sub = `${formatValue(s.unit, s.value, decimalsOf(t.sub.series))} ${t.sub.suffix}`;
      }
      need(!(t.sub_month && t.sub_quarter), slug, `tile "${t.label}" cannot have both sub_month and sub_quarter`);
      if (t.sub_month) sub = formatMonthYear(r.date);
      if (t.sub_quarter) sub = formatQuarterYear(r.date);
      need([t.sub_date, t.sub_month, t.sub_quarter, t.sub_period].filter(Boolean).length <= 1, slug, `tile "${t.label}" can have only one of sub_date, sub_month, sub_quarter and sub_period`);
      if (t.sub_date) sub = formatDate(r.date);
      if (t.sub_period) sub = (t.sub_prefix ?? '') + r.period; // the source's own period label, such as 2024-25 (sub_prefix: "Census " gives "Census 2021")
      need(t.sub_prefix === undefined || (typeof t.sub_prefix === 'string' && (t.sub_period || t.sub_quarter || t.sub_month || t.sub_date)), slug, `tile "${t.label}" has a sub_prefix without sub_period, sub_quarter, sub_month or sub_date (or one that is not text)`);
      if (t.sub_prefix !== undefined && !t.sub_period) sub = t.sub_prefix + sub; // words before the month, quarter or date
      const key = t.sub_month || t.sub_quarter || t.sub_date || t.sub_period ? t.label : `${t.label}, ${formatDate(r.date)}`;
      return { key, value: formatValue(r.unit, r.value, decimalsOf(t.series)), sub, isText: false };
    }
    if (t.from_status === true) {
      // a status tile: the status word from the metric's `status` block, and a sub-text, in the plain text style
      need(def.status !== undefined && STATUS_WORDS.includes(def.status.status), slug, `tile "${t.label}" reads the status but the metric has no "status" block with one of ${STATUS_WORDS.join(', ')}`);
      need(t.text === undefined, slug, `tile "${t.label}" has from_status and text`);
      return { key: t.label, value: def.status!.status, sub: t.sub_text ?? '', isText: true };
    }
    need(t.text !== undefined, slug, `tile "${t.label}" needs either series or text`);
    return { key: t.label, value: t.text!, sub: t.sub_text ?? '', isText: true };
  });

  // Full tables, newest first. `table` is one table (a row for every date in data.csv) or a list of tables (each has a row
  // for every date on which one of its own columns has a figure or a code, so a Census table and a yearly table can differ).
  const allDates = [...new Set(data.map((r) => r.date))].sort().reverse();
  const latestJuneAll = (picks: Pick[]) => latestJuneFor(picks);
  const tableDefs: TableDef[] = Array.isArray(def.table) ? def.table : [def.table];
  need(tableDefs.length > 0, slug, 'table is an empty list');
  const tables = tableDefs.map((td) => {
    need(Array.isArray(td.columns) && td.columns.length > 0, slug, 'a table has no columns');
    const colInfo = td.columns.map((c) => ({ unit: unitOf(c.series, c.jurisdiction, 'the table'), decimals: decimalsOf(c.series), c }));
    const realJune = td.columns.some((c) => c.derive === 'real')
      ? latestJuneAll(td.columns.filter((c) => c.derive === 'real'))
      : undefined;
    // period_format: month_year shows the row's date as "September 2026" (for tables that mix
    // quarterly and monthly series); missing: sets what a cell with no figure shows (default n/a).
    const fmt = td.period_format;
    need(fmt === undefined || fmt === 'period' || fmt === 'month_year', slug, 'table period_format must be period or month_year');
    const missingText = td.missing ?? 'n/a';
    const tableDates = Array.isArray(def.table)
      ? [...new Set(td.columns.flatMap((c) => [...rowsOf(c.series, c.jurisdiction, 'the table').keys()]))].sort().reverse()
      : allDates;
    const periodOf = (date: string) => data.find((r) => r.date === date)?.period ?? [...store.values()].map((m) => m.get(date)?.period).find((p) => p !== undefined)!;
    const rows = tableDates.map((date) => {
      const period = fmt === 'month_year' ? formatMonthYear(date) : periodOf(date);
      const cells = colInfo.map(({ unit, decimals, c }) => {
        const v = valueFor(c.series, c.jurisdiction, date, c.derive, realJune);
        if (v === undefined) {
          const raw = rowsOf(c.series, c.jurisdiction, 'the table').get(date);
          return raw?.isCode ? raw.valueText : missingText; // show the source's code as it is
        }
        return formatTable(unit, v, decimals);
      });
      return { period, cells };
    });
    return { headers: td.columns.map((c) => fill(c.header)), periodHeader: fill(td.period_header), rows };
  });

  // The state and territory panel. The places must be the eight jurisdictions in the fixed order, all on
  // one unit; the checker (scripts/validate.mjs) enforces the same rules before the build gets here.
  let panel: PanelData | undefined;
  if (def.state_panel === true) {
    const c = def.state_panel_config;
    need(c, slug, 'state_panel is true but state_panel_config is missing');
    need(Array.isArray(c.places) && c.places.length === STATE_ORDER.length, slug, `state_panel_config.places must list the ${STATE_ORDER.length} jurisdictions in the fixed order`);
    need(Array.isArray(c.headers) && c.headers.length === 3, slug, 'state_panel_config.headers must list three table headings (place, month, figure)');
    STATE_ORDER.forEach((want, i) => {
      need(c.places[i].jurisdiction === want.jurisdiction && c.places[i].abbreviation === want.abbreviation, slug, `state_panel_config place ${i + 1} must be ${want.jurisdiction} (${want.abbreviation}): the order is fixed`);
    });
    const unit = unitOf(c.series, c.national, 'the state panel');
    const numeric = (j: string) => [...rowsOf(c.series, j, 'the state panel').values()].filter((r) => !r.isCode).sort((a, b) => a.date.localeCompare(b.date));
    const pointsOf = (j: string) => numeric(j).map((r) => ({ date: r.date, period: r.period, value: r.value }));
    const places: PanelPlace[] = c.places.map((p) => {
      need(unitOf(c.series, p.jurisdiction, 'the state panel') === unit, slug, `the state panel mixes units (${p.jurisdiction})`);
      return { label: `${p.name} (${p.abbreviation})`, name: p.name, abbreviation: p.abbreviation, points: pointsOf(p.jurisdiction) };
    });
    const dateFmt = c.date_format ?? 'month_year';
    const extras = c.extra_columns ?? [];
    // `after: true` puts an extra column after the figure instead of before it
    const frequency = def.series.find((x) => x.id === c.series)?.frequency;
    need(frequency, slug, `the state panel series "${c.series}" has no frequency`);
    panel = {
      heading: fill(c.heading),
      note: fill(c.note),
      frequency: frequency!,
      unit,
      ...(decimalsOf(c.series) !== undefined ? { decimals: decimalsOf(c.series) } : {}),
      ...(c.y_range ? { yRange: { min: c.y_range.min, max: c.y_range.max } } : {}),
      ...(c.markers === true ? { markers: true } : {}),
      nationalLabel: c.national_label,
      national: pointsOf(c.national),
      places,
      figureHeader: fill(c.headers[2]),
      table: {
        headers: [c.headers[0], c.headers[1], ...extras.filter((x) => !x.after).map((x) => x.header), c.headers[2], ...extras.filter((x) => x.after).map((x) => x.header)].map((h) => fill(h)),
        rows: places.map((p, i) => {
          const last = p.points[p.points.length - 1];
          const jur = c.places[i].jurisdiction;
          // an extra column shows another series for the same place and date as the latest figure; own_latest: true shows
          // that series' own latest figure instead (and with_period: true adds its period label, such as "(2024-25)")
          const extraCell = (x: { series: string; own_latest?: boolean; with_period?: boolean }) => {
            const r = x.own_latest ? latestOf(x.series, jur, 'the state panel') : rowsOf(x.series, jur, 'the state panel').get(last.date);
            if (!r || r.isCode) return tableDefs[0].missing ?? 'n/a';
            return formatTable(r.unit, r.value, decimalsOf(x.series)) + (x.with_period ? ` (${r.period})` : '');
          };
          return {
            place: p.label,
            month: dateFmt === 'period' ? last.period : formatMonthYear(last.date),
            extras: extras.filter((x) => !x.after).map(extraCell),
            extrasAfter: extras.filter((x) => x.after).map(extraCell),
            value: formatValue(unit, last.value, decimalsOf(c.series)),
          };
        }),
      },
      governments,
      events,
    };
  }

  const link = (r: LedgerRow) => (r.link ? `<a href="${escapeHtml(r.link.url)}">${escapeHtml(r.link.label)}</a>` : '');
  const rich = (text: string, row?: LedgerRow) =>
    richText(text, {
      ...Object.fromEntries(Object.entries(textTokens).map(([k, v]) => [k, escapeHtml(v)])),
      ...(row ? { link: link(row), update: escapeHtml(def.update), retrieved: escapeHtml(formatDate(String(def.retrieved))) } : {}),
    });

  return {
    def,
    panel,
    tiles,
    chart: { alt: fill(def.chart_alt), source: fill(def.chart_source), views, governments, events },
    tables,
    rich: {
      banner: def.draft_banner ? rich(def.draft_banner) : '',
      meaning: def.meaning.map((p) => rich(p)),
      targets: def.targets.map((r) => ({ label: r.label, html: rich(r.text, r) })),
      sourcesMethod: def.sources_method.map((r) => ({ label: r.label, html: rich(r.text, r) })),
      care: def.read_with_care.map((p) => rich(p)),
      corrections: rich(def.corrections_text),
    },
  };
}
