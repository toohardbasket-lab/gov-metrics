import { readdirSync, statSync, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parse as parseYaml } from 'yaml';
import { parseCsv } from './csv';
import { formatDate, formatMonthYear, formatQuarterYear, formatTable, formatValue } from './format';
import { escapeHtml, fillPlain, richText } from './text';

const ROOT = process.cwd();

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
  series: { id: string; label: string }[];
  tiles: {
    label: string;
    series?: string;
    sub?: { series: string; suffix: string };
    months_back?: number;
    sub_month?: boolean;
    sub_quarter?: boolean;
    text?: string;
    sub_text?: string;
  }[];
  views: {
    id: string;
    label: string;
    derive: 'none' | 'real';
    lines: { series: string; label: string; color?: number }[];
    from?: number;
    target_band?: { min: number; max: number; label: string };
    caption: string;
  }[];
  chart_alt: string;
  chart_source: string;
  table: { period_header: string; period_format?: 'period' | 'month_year'; missing?: string; columns: { header: string; series: string; derive?: 'real' }[] };
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
  unit: string;
  status: string;
}

// Each line carries its own points, so lines of different frequencies can share one chart.
// `color` is 1 to 3 (the --series-N colours). `from` is the first year drawn, when the view starts
// later than the data. `band` is a shaded band across the plot (for example a target range).
export interface ChartLine {
  label: string;
  color: number;
  points: { date: string; period: string; value: number }[];
}
export interface ChartView {
  id: string;
  label: string;
  caption: string;
  unit: string;
  from?: number;
  band?: { min: number; max: number; label: string };
  lines: ChartLine[];
}
export interface ChartData {
  alt: string;
  source: string;
  views: ChartView[];
  governments: { date: string; party: string }[];
  events: { date: string; label: string }[];
}
export interface Metric {
  def: MetricDef;
  tiles: { key: string; value: string; sub: string; isText: boolean }[];
  chart: ChartData;
  table: { headers: string[]; periodHeader: string; rows: { period: string; cells: string[] }[] };
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
    const value = Number(r.value);
    if (r.value === '' || Number.isNaN(value)) throw new Error(`metrics/${slug}/data.csv: bad value "${r.value}" for ${r.series} ${r.date}`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(r.date)) throw new Error(`metrics/${slug}/data.csv: bad date "${r.date}"`);
    return { date: r.date, period: r.period, series: r.series, jurisdiction: r.jurisdiction, value, unit: r.unit, status: r.status };
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
  const bySeries = new Map<string, Map<string, DataRow>>();
  for (const r of data) {
    if (!bySeries.has(r.series)) bySeries.set(r.series, new Map());
    bySeries.get(r.series)!.set(r.date, r);
  }
  const seriesRows = (id: string, where: string) => {
    const m = bySeries.get(id);
    need(m && m.size > 0, slug, `${where} uses series "${id}" which has no rows in data.csv`);
    return m;
  };
  const unitOf = (id: string, where: string) => {
    const units = new Set([...seriesRows(id, where).values()].map((r) => r.unit));
    need(units.size === 1, slug, `series "${id}" has more than one unit`);
    return [...units][0];
  };
  for (const s of def.series) need(bySeries.has(s.id), slug, `series "${s.id}" is listed but has no rows in data.csv`);

  const { values: cpi, printed: cpiPrinted } = loadCpi();

  // Words the metric.yml text may use, filled in from the data (see metrics/README.md).
  // A token whose value cannot be worked out is left out, so using it stops the build.
  const dataDates = [...new Set(data.map((r) => r.date))].sort();
  const juneDates = dataDates.filter((d) => d.slice(5, 7) === '06');
  const textTokens: Record<string, string> = {
    first_year: dataDates[0].slice(0, 4),
    last_year: dataDates.at(-1)!.slice(0, 4),
    latest_period: data.find((r) => r.date === dataDates.at(-1))!.period,
  };
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
  const latestJuneFor = (ids: string[]) => {
    const dates = ids.flatMap((id) => [...seriesRows(id, 'a view').keys()]).filter((d) => d.slice(5, 7) === '06');
    need(dates.length > 0, slug, 'a real-terms view needs data dated in June');
    return dates.sort().at(-1)!;
  };
  const valueFor = (id: string, date: string, derive?: string, latestJune?: string): number | undefined => {
    const row = bySeries.get(id)?.get(date);
    if (!row) return undefined;
    return derive === 'real' ? realValue(row, latestJune!) : row.value;
  };

  // Chart views. Each line uses its own points (a series with no figure on a date has no point
  // there), so quarterly and monthly lines can share a chart.
  const views: ChartView[] = def.views.map((v) => {
    need(v.lines.length >= 1 && v.lines.length <= 3, slug, `view "${v.id}" must have one to three lines (the page defines three series colours)`);
    const units = new Set(v.lines.map((l) => unitOf(l.series, `view "${v.id}"`)));
    need(units.size === 1, slug, `view "${v.id}" mixes units; one scale per view`);
    const ids = v.lines.map((l) => l.series);
    const latestJune = v.derive === 'real' ? latestJuneFor(ids) : undefined;
    if (v.from !== undefined) need(Number.isInteger(v.from) && v.from > 1000 && v.from < 3000, slug, `view "${v.id}" has a "from" that is not a year`);
    const b = v.target_band;
    if (b !== undefined) {
      need(typeof b.min === 'number' && typeof b.max === 'number' && b.min < b.max, slug, `view "${v.id}" has a target_band whose min and max are not numbers with min below max`);
      need(typeof b.label === 'string' && b.label.trim() !== '', slug, `view "${v.id}" has a target_band with no label`);
    }
    const firstDate = v.from !== undefined ? `${v.from}-01-01` : '0000-01-01';
    const lines: ChartLine[] = v.lines.map((l, i) => {
      const color = l.color ?? i + 1;
      need(Number.isInteger(color) && color >= 1 && color <= 3, slug, `view "${v.id}" has a line colour that is not 1, 2 or 3`);
      const points: ChartLine['points'] = [];
      for (const date of [...bySeries.get(l.series)!.keys()].sort()) {
        if (date < firstDate) continue;
        const value = valueFor(l.series, date, v.derive, latestJune);
        if (value === undefined) continue;
        points.push({ date, period: bySeries.get(l.series)!.get(date)!.period, value });
      }
      need(points.length > 0, slug, `view "${v.id}" has no points for series "${l.series}"${v.from !== undefined ? ` from ${v.from}` : ''}`);
      return { label: l.label, color, points };
    });
    return {
      id: v.id, label: fill(v.label), caption: fill(v.caption), unit: [...units][0],
      ...(v.from !== undefined ? { from: v.from } : {}),
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
  const latestOf = (id: string, where: string) => {
    const m = seriesRows(id, where);
    const date = [...m.keys()].sort().at(-1)!;
    return m.get(date)!;
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
      let r = latestOf(t.series, 'a tile');
      if (t.months_back !== undefined) {
        need(Number.isInteger(t.months_back) && t.months_back > 0, slug, `tile "${t.label}" has a months_back that is not a whole number above zero`);
        const want = monthsBefore(r.date, t.months_back);
        const found = [...seriesRows(t.series, 'a tile').values()].find((x) => x.date.slice(0, 7) === want);
        need(found, slug, `tile "${t.label}" needs a figure for ${want}, ${t.months_back} months before ${r.date}, but data.csv has none`);
        r = found!;
      }
      need(!(t.sub && t.months_back !== undefined), slug, `tile "${t.label}" cannot have both sub and months_back`);
      let sub = '';
      if (t.sub) {
        const s = latestOf(t.sub.series, 'a tile');
        need(s.date === r.date, slug, `tile "${t.label}" and its sub series have different latest dates`);
        sub = `${formatValue(s.unit, s.value)} ${t.sub.suffix}`;
      }
      need(!(t.sub_month && t.sub_quarter), slug, `tile "${t.label}" cannot have both sub_month and sub_quarter`);
      if (t.sub_month) sub = formatMonthYear(r.date);
      if (t.sub_quarter) sub = formatQuarterYear(r.date);
      const key = t.sub_month || t.sub_quarter ? t.label : `${t.label}, ${formatDate(r.date)}`;
      return { key, value: formatValue(r.unit, r.value), sub, isText: false };
    }
    need(t.text !== undefined, slug, `tile "${t.label}" needs either series or text`);
    return { key: t.label, value: t.text!, sub: t.sub_text ?? '', isText: true };
  });

  // Full table, newest first.
  const allDates = [...new Set(data.map((r) => r.date))].sort().reverse();
  const colInfo = def.table.columns.map((c) => ({ unit: unitOf(c.series, 'the table'), c }));
  const latestJuneAll = (ids: string[]) => latestJuneFor(ids);
  const realJune = def.table.columns.some((c) => c.derive === 'real')
    ? latestJuneAll(def.table.columns.filter((c) => c.derive === 'real').map((c) => c.series))
    : undefined;
  // period_format: month_year shows the row's date as "September 2026" (for tables that mix
  // quarterly and monthly series); missing: sets what a cell with no figure shows (default n/a).
  const fmt = def.table.period_format;
  need(fmt === undefined || fmt === 'period' || fmt === 'month_year', slug, 'table period_format must be period or month_year');
  const missingText = def.table.missing ?? 'n/a';
  const rows = allDates.map((date) => {
    const period = fmt === 'month_year' ? formatMonthYear(date) : data.find((r) => r.date === date)!.period;
    const cells = colInfo.map(({ unit, c }) => {
      const v = valueFor(c.series, date, c.derive, realJune);
      return v === undefined ? missingText : formatTable(unit, v);
    });
    return { period, cells };
  });

  const link = (r: LedgerRow) => (r.link ? `<a href="${escapeHtml(r.link.url)}">${escapeHtml(r.link.label)}</a>` : '');
  const rich = (text: string, row?: LedgerRow) =>
    richText(text, {
      ...Object.fromEntries(Object.entries(textTokens).map(([k, v]) => [k, escapeHtml(v)])),
      ...(row ? { link: link(row), update: escapeHtml(def.update), retrieved: escapeHtml(formatDate(String(def.retrieved))) } : {}),
    });

  return {
    def,
    tiles,
    chart: { alt: fill(def.chart_alt), source: fill(def.chart_source), views, governments, events },
    table: { headers: def.table.columns.map((c) => fill(c.header)), periodHeader: fill(def.table.period_header), rows },
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
