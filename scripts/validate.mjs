#!/usr/bin/env node
// Checks every metric and the shared files, and refuses to pass if anything is wrong.
//
//   npm run validate                  run every check (the build runs this first)
//   npm run accept-data               run every check, then record the data as accepted
//   node scripts/validate.mjs --root <folder>   check a copy of the project (used by the tests)
//
// Exit code 0 only if every check passes. Every problem is printed, one line each.
// Plain JavaScript, no new packages: it uses the `yaml` package the site already has.

import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse as parseYaml } from 'yaml';

// ---------------------------------------------------------------- settings

const HEADER = 'date,period,series,jurisdiction,value,unit,status';
const STATUSES = ['actual', 'estimate', 'forecast'];

// The units the site knows how to format. This is a copy of the list in src/lib/format.ts
// (formatValue, formatAxis and formatTable). A check below fails if the two lists differ,
// so a new unit has to be added in both places.
const KNOWN_UNITS = ['aud_million', 'pct_gdp'];

// How far apart consecutive rows must be. To add quarterly or monthly data, add an entry here
// whose `next` returns the date that should follow the one given (for example three months
// later, keeping the end of the month). Nothing else in this file needs to change.
const FREQUENCIES = {
  annual: {
    next(iso) {
      const [y, m, d] = iso.split('-');
      return `${String(+y + 1).padStart(4, '0')}-${m}-${d}`;
    },
  },
};

// What the page (src/lib/metrics.ts and src/pages/metrics/[slug].astro) reads from metric.yml,
// plus slug (must match the folder), jurisdiction and draft.
const REQUIRED_FIELDS = [
  'slug', 'title', 'theme', 'jurisdiction', 'lede', 'draft', 'series', 'tiles', 'views',
  'chart_alt', 'chart_source', 'table', 'meaning', 'targets', 'sources_method',
  'read_with_care', 'corrections_text', 'update', 'retrieved',
];

const CPI_MAX_YEARLY_CHANGE = 0.3;
const IGNORED_FILES = new Set(['.DS_Store', 'Thumbs.db', 'desktop.ini']);

// ---------------------------------------------------------------- small helpers

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');
// The checksum of a text file ignores Windows line endings, so a copy of the project checked out
// on Windows gives the same answer as one checked out on Linux.
const textSha256 = (buf) => sha256(Buffer.from(buf.toString('utf8').replace(/\r\n/g, '\n'), 'utf8'));

function isRealDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return false;
  const [y, mo, d] = [+m[1], +m[2], +m[3]];
  const t = new Date(Date.UTC(y, mo - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
}

const isNum = (x) => typeof x === 'number' && Number.isFinite(x);
const byDate = (a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0);

function listFiles(dir, prefix = '') {
  const out = [];
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...listFiles(p, `${prefix}${name}/`));
    else out.push(`${prefix}${name}`);
  }
  return out;
}

// Reads a small CSV for the shared files. Returns { rows: [{line, cells}] } or null after
// recording the problem.
function readSimpleCsv(path, label, wantHeader, F) {
  if (!existsSync(path)) {
    F.fail(`${label}: the file is missing.`);
    return null;
  }
  const text = readFileSync(path, 'utf8');
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  if (lines.at(-1) === '') lines.pop();
  if (lines.length === 0) {
    F.fail(`${label}: the file is empty.`);
    return null;
  }
  const quoteAt = lines.findIndex((l) => l.includes('"'));
  if (quoteAt >= 0) F.fail(`${label}: line ${quoteAt + 1} contains a quote character. The site cannot read quoted fields.`);
  if (lines[0].trim() !== wantHeader) {
    F.fail(`${label}: the header is "${lines[0].trim()}" but must be exactly "${wantHeader}".`);
    return null;
  }
  const width = wantHeader.split(',').length;
  const rows = [];
  lines.slice(1).forEach((raw, i) => {
    const line = i + 2;
    if (raw.trim() === '') return F.fail(`${label}: line ${line} is blank.`);
    const cells = raw.split(',').map((c) => c.trim());
    if (cells.length !== width) return F.fail(`${label}: line ${line} has ${cells.length} fields but the header has ${width}.`);
    rows.push({ line, cells });
  });
  return { rows };
}

// Collects problems and warnings. `scope` says which metric (or "shared files") a problem belongs
// to, so a metric that passes can be reported as passing.
function makeReport() {
  const fails = [];
  const warns = [];
  const scoped = (scope) => ({
    fail: (msg, kind = 'check') => fails.push({ scope, msg, kind }),
    warn: (msg) => warns.push({ scope, msg }),
  });
  return { fails, warns, scoped };
}

// ---------------------------------------------------------------- one metric

function loadDefinition(root, slug, F) {
  const path = `metrics/${slug}/metric.yml`;
  let def;
  try {
    def = parseYaml(readFileSync(join(root, path), 'utf8'));
  } catch (e) {
    F.fail(`${path}: could not be read as YAML (${String(e.message).split('\n')[0]}).`);
    return null;
  }
  if (!def || typeof def !== 'object' || Array.isArray(def)) {
    F.fail(`${path}: the file is not a list of fields.`);
    return null;
  }
  for (const k of REQUIRED_FIELDS) {
    if (def[k] === undefined || def[k] === null) F.fail(`${path}: required field "${k}" is missing.`);
  }
  if (def.slug !== undefined && def.slug !== slug) F.fail(`${path}: slug "${def.slug}" does not match the folder name "${slug}".`);
  if (def.draft !== undefined && def.draft !== null && typeof def.draft !== 'boolean') F.fail(`${path}: "draft" must be true or false.`);
  if (def.draft === true && !def.draft_banner) F.fail(`${path}: "draft" is true but "draft_banner" is missing.`);
  if (def.series !== undefined && def.series !== null && !Array.isArray(def.series)) F.fail(`${path}: "series" must be a list.`);
  if (def.views !== undefined && def.views !== null && !Array.isArray(def.views)) F.fail(`${path}: "views" must be a list.`);
  return def;
}

// Reads data.csv. Returns the rows that are good enough to check further, plus a checksum.
function loadDataCsv(root, slug, F) {
  const path = `metrics/${slug}/data.csv`;
  const full = join(root, path);
  if (!existsSync(full)) {
    F.fail(`${path}: the file is missing.`);
    return null;
  }
  const buf = readFileSync(full);
  const lines = buf.toString('utf8').replace(/\r\n?/g, '\n').split('\n');
  if (lines.at(-1) === '') lines.pop();
  const sha = textSha256(buf);
  if (lines.length === 0) {
    F.fail(`${path}: the file is empty.`);
    return { rows: [], sha };
  }
  const quoteAt = lines.findIndex((l) => l.includes('"'));
  if (quoteAt >= 0) F.fail(`${path}: line ${quoteAt + 1} contains a quote character. The site cannot read quoted fields.`);
  if (lines[0].trim() !== HEADER) {
    F.fail(`${path}: the header is "${lines[0].trim()}" but must be exactly "${HEADER}".`);
    return { rows: [], sha };
  }
  const rows = [];
  const seen = new Map();
  lines.slice(1).forEach((raw, i) => {
    const line = i + 2;
    if (raw.trim() === '') return F.fail(`${path}: line ${line} is blank.`);
    const cells = raw.split(',').map((c) => c.trim());
    if (cells.length !== 7) return F.fail(`${path}: line ${line} has ${cells.length} fields but must have 7.`);
    const [date, period, series, jurisdiction, valueText, unit, status] = cells;
    const where = `${path}: line ${line}, ${series || '(no series)'} (${jurisdiction || 'no jurisdiction'}) on ${date || '(no date)'}`;
    let good = true;
    if (!isRealDate(date)) { F.fail(`${where}: "${date}" is not a real date in the form YYYY-MM-DD.`); good = false; }
    if (!series) { F.fail(`${where}: the series is empty.`); good = false; }
    if (!jurisdiction) { F.fail(`${where}: the jurisdiction is empty.`); good = false; }
    const value = /^-?\d+(\.\d+)?$/.test(valueText) ? Number(valueText) : NaN;
    if (!Number.isFinite(value)) { F.fail(`${where}: the value "${valueText}" is not a number.`); good = false; }
    if (!STATUSES.includes(status)) { F.fail(`${where}: the status "${status}" is not one of ${STATUSES.join(', ')}.`); good = false; }
    if (!KNOWN_UNITS.includes(unit)) { F.fail(`${where}: the unit "${unit}" is not one the site can format (${KNOWN_UNITS.join(', ')}).`); good = false; }
    if (good) {
      const key = `${date}|${series}|${jurisdiction}`;
      if (seen.has(key)) {
        F.fail(`${where}: duplicate of line ${seen.get(key)}. Each date, series and jurisdiction may appear once.`);
        good = false;
      } else seen.set(key, line);
    }
    if (good) rows.push({ line, date, period, series, jurisdiction, value, unit, status });
  });
  return { rows, sha };
}

function seriesNamedInViews(def) {
  const used = new Map(); // series id -> where it is named
  const add = (id, where) => { if (typeof id === 'string' && !used.has(id)) used.set(id, where); };
  if (Array.isArray(def.views)) {
    for (const v of def.views) for (const l of v?.lines ?? []) add(l?.series, `view "${v.id}"`);
  }
  if (Array.isArray(def.tiles)) {
    for (const t of def.tiles) { add(t?.series, `tile "${t.label}"`); add(t?.sub?.series, `tile "${t.label}"`); }
  }
  for (const c of def.table?.columns ?? []) add(c?.series, 'the table');
  return used;
}

function groupRows(rows) {
  const groups = new Map(); // "series|jurisdiction" -> rows, oldest first
  for (const r of rows) {
    const k = `${r.series}|${r.jurisdiction}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  for (const g of groups.values()) g.sort(byDate);
  return groups;
}

function checkSeries(slug, def, data, groups, F) {
  const path = `metrics/${slug}/data.csv`;
  const yml = `metrics/${slug}/metric.yml`;
  const declared = new Map();
  for (const s of Array.isArray(def.series) ? def.series : []) {
    if (!s || typeof s.id !== 'string') { F.fail(`${yml}: a series has no id.`); continue; }
    if (declared.has(s.id)) F.fail(`${yml}: series "${s.id}" is listed twice.`);
    declared.set(s.id, s);
  }
  const inData = new Set(data.rows.map((r) => r.series));

  // 4. series match in both directions
  for (const [id, where] of seriesNamedInViews(def)) {
    if (!inData.has(id)) F.fail(`${yml}: ${where} uses series "${id}", which has no rows in data.csv.`);
    if (!declared.has(id)) F.fail(`${yml}: ${where} uses series "${id}", which is not in the "series" list.`);
  }
  for (const id of inData) {
    if (!declared.has(id)) F.fail(`${path}: series "${id}" is in data.csv but is not declared in the "series" list in metric.yml.`);
  }
  for (const id of declared.keys()) {
    if (!inData.has(id)) F.fail(`${yml}: series "${id}" is declared but has no rows in data.csv.`);
  }

  for (const [id, s] of declared) {
    if (!inData.has(id)) continue;
    const seriesGroups = [...groups.entries()].filter(([k]) => k.startsWith(`${id}|`)).map(([, g]) => g);

    // 5. frequency and gaps
    const freq = FREQUENCIES[s.frequency];
    if (s.frequency === undefined) F.fail(`${yml}: series "${id}" has no "frequency". Add one of: ${Object.keys(FREQUENCIES).join(', ')}.`);
    else if (!freq) F.fail(`${yml}: series "${id}" has frequency "${s.frequency}", which the validator does not know. Known: ${Object.keys(FREQUENCIES).join(', ')}.`);
    else {
      for (const g of seriesGroups) {
        let reported = 0;
        for (let i = 1; i < g.length; i++) {
          const a = g[i - 1].date;
          const b = g[i].date;
          let exp = freq.next(a);
          const missing = [];
          let steps = 0;
          while (exp < b && steps++ < 2000) { missing.push(exp); exp = freq.next(exp); }
          if (exp === b && missing.length === 0) continue;
          if (++reported > 10) break;
          if (exp === b) F.fail(`${path}: ${id} (${g[0].jurisdiction}) is missing ${missing.join(', ')}; the rows jump from ${a} to ${b}.`);
          else F.fail(`${path}: ${id} (${g[0].jurisdiction}) has a row on ${b} (line ${g[i].line}) which is not on the ${s.frequency} schedule after ${a}; expected ${freq.next(a)}.`);
        }
      }
    }

    // 6. plausible range, and the optional step limit
    const p = s.plausible;
    const hasRange = p && typeof p === 'object' && isNum(p.min) && isNum(p.max) && p.min <= p.max;
    if (!hasRange) F.fail(`${yml}: series "${id}" needs "plausible" with a numeric min and max (min not above max).`);
    else {
      for (const g of seriesGroups) {
        for (const r of g) {
          if (r.value < p.min || r.value > p.max) {
            F.fail(`${path}: line ${r.line}, ${id} (${r.jurisdiction}) on ${r.date} is ${r.value}, outside the plausible range ${p.min} to ${p.max} set in metric.yml.`);
          }
        }
      }
    }
    if (s.max_step_pct !== undefined) {
      const floor = s.max_step_floor === undefined ? 0 : s.max_step_floor;
      if (!isNum(s.max_step_pct) || s.max_step_pct <= 0) F.fail(`${yml}: series "${id}" has a "max_step_pct" that is not a positive number.`);
      else if (!isNum(floor) || floor < 0) F.fail(`${yml}: series "${id}" has a "max_step_floor" that is not a number of zero or more.`);
      else {
        for (const g of seriesGroups) {
          for (let i = 1; i < g.length; i++) {
            const prev = Math.abs(g[i - 1].value);
            if (prev < floor || prev === 0) continue;
            const pct = (Math.abs(g[i].value - g[i - 1].value) / prev) * 100;
            if (pct > s.max_step_pct) {
              F.fail(`${path}: line ${g[i].line}, ${id} (${g[i].jurisdiction}) on ${g[i].date} moves ${pct.toFixed(1)} per cent from ${g[i - 1].value} on ${g[i - 1].date}, more than the limit of ${s.max_step_pct} per cent set in metric.yml.`);
            }
          }
        }
      }
    }
  }
}

// 7. rows never fall
function lockFromGroups(groups, sha) {
  const series = [...groups.values()]
    .map((g) => ({ series: g[0].series, jurisdiction: g[0].jurisdiction, rows: g.length, first: g[0].date, last: g.at(-1).date }))
    .sort((a, b) => (a.series < b.series ? -1 : a.series > b.series ? 1 : a.jurisdiction < b.jurisdiction ? -1 : 1));
  return { data_sha256: sha, series };
}

function checkLock(root, slug, groups, sha, F) {
  const path = `metrics/${slug}/data.lock.json`;
  const full = join(root, path);
  if (!existsSync(full)) {
    F.fail(`${path}: there is no lock file. Run "npm run accept-data" to record the data as accepted.`, 'lock-missing');
    return;
  }
  let lock;
  try {
    lock = JSON.parse(readFileSync(full, 'utf8'));
    if (!lock || !Array.isArray(lock.series) || typeof lock.data_sha256 !== 'string') throw new Error('wrong shape');
  } catch {
    F.fail(`${path}: the lock file cannot be read. Run "npm run accept-data" to write a new one.`, 'lock-missing');
    return;
  }
  const hint = ' If this is deliberate, delete data.lock.json and run "npm run accept-data".';
  let bad = 0;
  for (const l of lock.series) {
    const g = groups.get(`${l.series}|${l.jurisdiction}`);
    if (!g || g.length === 0) {
      bad++;
      F.fail(`${path}: ${l.series} (${l.jurisdiction}) had ${l.rows} rows when the data was last accepted but has none now.${hint}`);
      continue;
    }
    if (g.length < l.rows) { bad++; F.fail(`${path}: ${l.series} (${l.jurisdiction}) has ${g.length} rows, fewer than the ${l.rows} recorded when the data was last accepted. Rows must never fall.${hint}`); }
    if (g[0].date > l.first) { bad++; F.fail(`${path}: ${l.series} (${l.jurisdiction}) now starts on ${g[0].date}, later than the ${l.first} recorded when the data was last accepted.${hint}`); }
    if (g.at(-1).date < l.last) { bad++; F.fail(`${path}: ${l.series} (${l.jurisdiction}) now ends on ${g.at(-1).date}, earlier than the ${l.last} recorded when the data was last accepted.${hint}`); }
  }
  if (bad === 0 && lock.data_sha256 !== sha) {
    F.warn(`metrics/${slug}/data.csv: data has changed since it was last accepted. If the changes are expected, check them against the source and run "npm run accept-data".`);
  }
}

// 8. source files
function checkSources(root, dirRel, F) {
  const dir = join(root, dirRel);
  const manifestRel = `${dirRel}/manifest.json`;
  if (!existsSync(join(dir, 'manifest.json'))) {
    F.fail(`${manifestRel}: the manifest is missing, so the downloaded source files cannot be checked.`);
    return;
  }
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'));
    if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('not an object');
  } catch {
    F.fail(`${manifestRel}: the manifest cannot be read as JSON.`);
    return;
  }
  for (const [name, info] of Object.entries(manifest)) {
    const rel = `${dirRel}/${name}`;
    if (name.includes('/') || name.includes('\\') || name.includes('..') || name === 'manifest.json') {
      F.fail(`${manifestRel}: the entry "${name}" is not a plain file name in this folder.`);
      continue;
    }
    const file = join(dir, name);
    if (!existsSync(file)) { F.fail(`${rel}: listed in the manifest but the file is missing.`); continue; }
    if (!info || typeof info.sha256 !== 'string' || !isNum(info.bytes)) { F.fail(`${manifestRel}: the entry for "${name}" has no sha256 and bytes.`); continue; }
    const buf = readFileSync(file);
    if (buf.length !== info.bytes) F.fail(`${rel}: the file is ${buf.length} bytes but the manifest says ${info.bytes}. The file has changed since it was downloaded.`);
    else if (sha256(buf) !== info.sha256) F.fail(`${rel}: the checksum does not match the manifest (file ${sha256(buf).slice(0, 12)}..., manifest ${info.sha256.slice(0, 12)}...). The file has changed since it was downloaded.`);
  }
  for (const f of listFiles(dir)) {
    if (f === 'manifest.json' || IGNORED_FILES.has(f.split('/').at(-1))) continue;
    if (!Object.hasOwn(manifest, f)) F.fail(`${dirRel}/${f}: this file is in the sources folder but is not listed in manifest.json.`);
  }
}

// ---------------------------------------------------------------- shared files

function checkShared(root, F) {
  // governments.csv and events.csv: real dates, ascending
  for (const [file, header] of [['governments.csv', 'sworn_in,party,note'], ['events.csv', 'date,label']]) {
    const label = `shared/${file}`;
    const csv = readSimpleCsv(join(root, 'shared', file), label, header, F);
    if (!csv) continue;
    let prev = null;
    for (const { line, cells } of csv.rows) {
      const d = cells[0];
      if (!isRealDate(d)) { F.fail(`${label}: line ${line}: "${d}" is not a real date in the form YYYY-MM-DD.`); continue; }
      if (prev !== null && d <= prev) F.fail(`${label}: line ${line}: ${d} is not after ${prev}. Dates must be in ascending order.`);
      prev = d;
    }
  }

  // cpi_june.csv
  const cpi = new Map();
  const label = 'shared/cpi_june.csv';
  const csv = readSimpleCsv(join(root, 'shared', 'cpi_june.csv'), label, 'date,index,base', F);
  if (csv) {
    const years = [];
    for (const { line, cells } of csv.rows) {
      const [d, idx] = cells;
      const m = /^(\d{4})-06-30$/.exec(d);
      if (!m || !isRealDate(d)) { F.fail(`${label}: line ${line}: "${d}" is not a 30 June date.`); continue; }
      if (cpi.has(d)) { F.fail(`${label}: line ${line}: ${d} appears more than once.`); continue; }
      const n = /^\d+(\.\d+)?$/.test(idx) ? Number(idx) : NaN;
      if (!(n > 0)) { F.fail(`${label}: line ${line}: the index "${idx}" for ${d} is not a positive number.`); continue; }
      cpi.set(d, n);
      years.push(+m[1]);
    }
    years.sort((a, b) => a - b);
    for (let i = 1; i < years.length; i++) {
      for (let y = years[i - 1] + 1; y < years[i]; y++) F.fail(`${label}: the 30 June ${y} row is missing.`);
      if (years[i] === years[i - 1] + 1) {
        const a = cpi.get(`${years[i - 1]}-06-30`);
        const b = cpi.get(`${years[i]}-06-30`);
        const change = Math.abs(b / a - 1);
        if (change > CPI_MAX_YEARLY_CHANGE) F.fail(`${label}: the index moves ${(change * 100).toFixed(1)} per cent between ${years[i - 1]}-06-30 (${a}) and ${years[i]}-06-30 (${b}), more than the ${CPI_MAX_YEARLY_CHANGE * 100} per cent allowed.`);
      }
    }
  }
  return cpi;
}

// Is the unit list in format.ts the same as KNOWN_UNITS? Skipped when the folder has no src/lib/format.ts.
function checkFormatUnits(root, F) {
  const path = join(root, 'src', 'lib', 'format.ts');
  if (!existsSync(path)) return;
  const found = new Set([...readFileSync(path, 'utf8').matchAll(/unit === '([a-z_]+)'/g)].map((m) => m[1]));
  const a = [...found].sort().join(', ');
  const b = [...KNOWN_UNITS].sort().join(', ');
  if (a !== b) F.fail(`src/lib/format.ts: formats the units [${a}] but scripts/validate.mjs lists [${b}]. Keep the two lists the same.`);
}

// ---------------------------------------------------------------- everything

function validateRoot(root) {
  const report = makeReport();
  const passes = []; // one line per metric that passed
  const locks = new Map(); // slug -> lock object to write on accept

  const metricsDir = join(root, 'metrics');
  const slugs = existsSync(metricsDir)
    ? readdirSync(metricsDir).filter((n) => statSync(join(metricsDir, n)).isDirectory() && existsSync(join(metricsDir, n, 'metric.yml'))).sort()
    : [];
  const SH = report.scoped('shared files');
  if (slugs.length === 0) SH.fail('metrics: no metric folders with a metric.yml were found.');

  const cpi = checkShared(root, SH);
  checkSources(root, 'shared/sources', SH);
  checkFormatUnits(root, SH);

  for (const slug of slugs) {
    const F = report.scoped(slug);
    const def = loadDefinition(root, slug, F);
    const data = loadDataCsv(root, slug, F);
    if (data) {
      const groups = groupRows(data.rows);
      if (def) checkSeries(slug, def, data, groups, F);
      checkLock(root, slug, groups, data.sha, F);
      locks.set(slug, lockFromGroups(groups, data.sha));

      // 10. every date used by an inflation-adjusted view has a price index
      if (def) {
        const realSeries = new Set();
        for (const v of Array.isArray(def.views) ? def.views : []) {
          if (v?.derive === 'real') for (const l of v.lines ?? []) realSeries.add(l.series);
        }
        for (const c of def.table?.columns ?? []) if (c?.derive === 'real') realSeries.add(c.series);
        for (const id of realSeries) {
          const missing = [...new Set(data.rows.filter((r) => r.series === id).map((r) => r.date))].filter((d) => !cpi.has(d));
          if (missing.length > 0) {
            F.fail(`metrics/${slug}/metric.yml: ${id} is shown in inflation-adjusted dollars, but shared/cpi_june.csv has no price index for ${missing.slice(0, 6).join(', ')}${missing.length > 6 ? ` and ${missing.length - 6} more` : ''}.`);
          }
        }
      }
    }
    checkSources(root, `metrics/${slug}/sources`, F);

    if (!report.fails.some((f) => f.scope === slug)) {
      const rows = data.rows;
      const dates = rows.map((r) => r.date).sort();
      const ids = new Set(rows.map((r) => r.series));
      passes.push(`PASS ${slug}: ${rows.length} rows, ${ids.size} series, ${dates[0]} to ${dates.at(-1)}. All checks passed.`);
    }
  }
  if (!report.fails.some((f) => f.scope === 'shared files')) {
    passes.push(`PASS shared files: governments, events, price index (${cpi.size} Junes) and source files are in order.`);
  }
  return { fails: report.fails, warns: report.warns, passes, locks, slugs };
}

// ---------------------------------------------------------------- command line

function main(argv) {
  let root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  let accept = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--root') {
      if (!argv[i + 1]) { console.error('--root needs a folder.'); return 2; }
      root = resolve(argv[++i]);
    } else if (argv[i] === '--accept') accept = true;
    else { console.error(`Unknown option ${argv[i]}. Use --root <folder> or --accept.`); return 2; }
  }

  const r = validateRoot(root);
  // When accepting, a missing lock file is not a problem: writing it is the point.
  const blocking = r.fails.filter((f) => !(accept && f.kind === 'lock-missing'));

  for (const p of r.passes) console.log(p);
  for (const w of r.warns) console.log(`WARNING: ${w.msg}`);
  for (const f of blocking) console.log(`FAIL: ${f.msg}`);

  const warnText = r.warns.length ? `, ${r.warns.length} warning${r.warns.length === 1 ? '' : 's'}` : '';
  if (blocking.length > 0) {
    console.log(`Validation failed: ${blocking.length} problem${blocking.length === 1 ? '' : 's'} found${warnText}.`);
    if (accept) console.log('Nothing was accepted. Fix the problems above first; the lock files were not changed.');
    return 1;
  }
  if (accept) {
    for (const [slug, lock] of r.locks) {
      writeFileSync(join(root, 'metrics', slug, 'data.lock.json'), JSON.stringify(lock, null, 2) + '\n');
      console.log(`Accepted metrics/${slug}/data.csv: wrote metrics/${slug}/data.lock.json (${lock.series.length} series, ${lock.series.reduce((n, s) => n + s.rows, 0)} rows).`);
    }
    return 0;
  }
  console.log(`Validation passed: ${r.slugs.length} metric${r.slugs.length === 1 ? '' : 's'} and the shared files, no problems${warnText}.`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));
