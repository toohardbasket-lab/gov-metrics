#!/usr/bin/env node
// Checks every metric and the shared files, and refuses to pass if anything is wrong.
//
//   npm run validate                  run every check (the build runs this first)
//   npm run accept-data               run every check, then record the data as accepted
//   npm run accept-data -- --accept-revisions   the same, and also accept large revisions to past figures
//   npm run accept-revisions          the same as the line above, as a script of its own
//   node scripts/validate.mjs --root <folder>   check a copy of the project (used by the tests)
//
// Exit code 0 only if every check passes. Every problem is printed, one line each.
// Plain JavaScript, no new packages: it uses the `yaml` package the site already has.

import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse as parseYaml } from 'yaml';
import { computeDerived, deriveInputs, deriveProblems, isRealIsoDate, isValueCode } from '../src/lib/derive.mjs';
import { STATUS_WORDS } from '../src/lib/status.mjs';
import { STATE_ORDER } from '../src/lib/jurisdictions.mjs';

// ---------------------------------------------------------------- settings

const HEADER = 'date,period,series,jurisdiction,value,unit,status';
const STATUSES = ['actual', 'estimate', 'forecast'];

// The units the site knows how to format. This is a copy of the list in src/lib/format.ts
// (formatValue, formatAxis and formatTable). A check below fails if the two lists differ,
// so a new unit has to be added in both places.
const KNOWN_UNITS = ['aud_million', 'pct_gdp', 'pct', 'index', 'count', 'rate', 'days', 'per_day'];

// How far apart consecutive rows must be. To add another frequency, add an entry here
// whose `next` returns the date that should follow the one given (for example three months
// later, keeping the end of the month). Nothing else in this file needs to change.
const FREQUENCIES = {
  annual: {
    next(iso) {
      const [y, m, d] = iso.split('-');
      return `${String(+y + 1).padStart(4, '0')}-${m}-${d}`;
    },
  },
  // Monthly data sits on the last day of each month (28 or 29 February, 30 April, and so on).
  // `next` gives the last day of the month after the one given. `onSchedule` says whether a
  // single date is allowed at all for this frequency.
  monthly: {
    next(iso) {
      const [y, m] = iso.split('-').map(Number);
      const ny = m === 12 ? y + 1 : y;
      const nm = m === 12 ? 1 : m + 1;
      const last = new Date(Date.UTC(ny, nm, 0)).getUTCDate(); // day 0 of the month after is its last day
      return `${String(ny).padStart(4, '0')}-${String(nm).padStart(2, '0')}-${String(last).padStart(2, '0')}`;
    },
    onSchedule(iso) {
      const [y, m, d] = iso.split('-').map(Number);
      return d === new Date(Date.UTC(y, m, 0)).getUTCDate();
    },
    scheduleHint: 'the last day of a month',
  },
  // Quarterly data sits on the last day of March, June, September and December (31 March, 30 June,
  // 30 September, 31 December). `next` gives the last day of the quarter after the one given.
  quarterly: {
    next(iso) {
      const [y, m] = iso.split('-').map(Number);
      const total = y * 12 + (m - 1) + 3; // three months on
      const ny = Math.floor(total / 12);
      const nm = (total % 12) + 1;
      const last = new Date(Date.UTC(ny, nm, 0)).getUTCDate();
      return `${String(ny).padStart(4, '0')}-${String(nm).padStart(2, '0')}-${String(last).padStart(2, '0')}`;
    },
    onSchedule(iso) {
      const [y, m, d] = iso.split('-').map(Number);
      return m % 3 === 0 && d === new Date(Date.UTC(y, m, 0)).getUTCDate();
    },
    scheduleHint: 'the last day of March, June, September or December',
  },
  // A Census is held every five years, on a night that moves by a few days (9 August 2011, 9 August 2016,
  // 10 August 2021). `next` is the same day five years on; a date within `toleranceDays` of it counts as on
  // schedule. A missing Census (a gap of ten years) is still refused.
  census: {
    next(iso) {
      const [y, m, d] = iso.split('-');
      return `${String(+y + 5).padStart(4, '0')}-${m}-${d}`;
    },
    toleranceDays: 7,
  },
};

// Days between two ISO dates (whole days; the dates are real, checked before this is used).
const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);

// What the page (src/lib/metrics.ts and src/pages/metrics/[slug].astro) reads from metric.yml,
// plus slug (must match the folder), jurisdiction and draft.
const REQUIRED_FIELDS = [
  'slug', 'title', 'theme', 'jurisdiction', 'lede', 'draft', 'series', 'tiles', 'views',
  'chart_alt', 'chart_source', 'table', 'meaning', 'targets', 'sources_method',
  'read_with_care', 'corrections_text', 'update', 'retrieved',
];

// The version of the lock file written by this checker. Version 2 stores every accepted value.
const LOCK_VERSION = 2;
const REVISION_KEYS = ['max_abs', 'max_pct', 'pct_floor'];
const REVISION_HINT = 'If this revision is genuine, check it against the source and accept it with: npm run accept-data -- --accept-revisions';

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
    fail: (msg, kind = 'check', extra = {}) => fails.push({ scope, msg, kind, ...extra }),
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
  if (Array.isArray(def.views)) {
    for (const v of def.views) if (v && v.markers !== undefined && typeof v.markers !== 'boolean') F.fail(`${path}: view "${v.id}" has a "markers" that is not true or false.`);
  }
  if (Array.isArray(def.views)) {
    for (const v of def.views) {
      if (!v || typeof v !== 'object') continue;
      // `to`: the last date the axis shows; `reference_lines`: horizontal lines at a value (a target); `dash` on a line
      if (v.to !== undefined && !isRealIsoDate(v.to)) F.fail(`${path}: view "${v.id}" has a "to" that is not a real date written YYYY-MM-DD.`);
      if (v.to !== undefined && isRealIsoDate(v.to) && Number.isInteger(v.from) && v.to <= `${v.from}-01-01`) F.fail(`${path}: view "${v.id}" has a "to" date that is not after its "from" year.`);
      if (v.reference_lines !== undefined) {
        if (!Array.isArray(v.reference_lines) || v.reference_lines.length === 0) F.fail(`${path}: view "${v.id}" has "reference_lines" that is not a list of {value, label, style}.`);
        else {
          for (const r of v.reference_lines) {
            if (!r || typeof r !== 'object' || Array.isArray(r) || Object.keys(r).some((k) => !['value', 'label', 'style'].includes(k))) { F.fail(`${path}: view "${v.id}" has a reference line that is not {value, label, style}.`); continue; }
            if (!isNum(r.value)) F.fail(`${path}: view "${v.id}" has a reference line whose "value" is not a number.`);
            if (typeof r.label !== 'string' || r.label.trim() === '') F.fail(`${path}: view "${v.id}" has a reference line with no "label".`);
            if (r.style !== 'solid' && r.style !== 'dashed') F.fail(`${path}: view "${v.id}" has a reference line whose "style" is not solid or dashed.`);
          }
        }
      }
      for (const l of Array.isArray(v.lines) ? v.lines : []) {
        if (l && l.dash !== undefined && typeof l.dash !== 'boolean') F.fail(`${path}: view "${v.id}" has a line whose "dash" is not true or false.`);
      }
    }
  }
  // `status`: the official status of the target, in a form a Targets page can read (plan section 4)
  if (def.status !== undefined) {
    const st = def.status;
    if (!st || typeof st !== 'object' || Array.isArray(st) || Object.keys(st).some((k) => !['status', 'assessed_by', 'assessed_on', 'due'].includes(k))) {
      F.fail(`${path}: "status" must be {status, assessed_by, assessed_on, due}.`);
    } else {
      if (!STATUS_WORDS.includes(st.status)) F.fail(`${path}: status "${st.status}" is not one of ${STATUS_WORDS.join(', ')}.`);
      if (typeof st.assessed_by !== 'string' || st.assessed_by.trim() === '') F.fail(`${path}: "status" needs "assessed_by", as text (who rated it).`);
      if (typeof st.assessed_on !== 'string' || !/^\d{4}-(0[1-9]|1[0-2])(-\d{2})?$/.test(st.assessed_on) || (st.assessed_on.length === 10 && !isRealIsoDate(st.assessed_on))) F.fail(`${path}: "status" needs "assessed_on", a month YYYY-MM or a date YYYY-MM-DD, written as text.`);
      if (!isRealIsoDate(st.due)) F.fail(`${path}: "status" needs "due", a real date written YYYY-MM-DD.`);
    }
  }
  if (Array.isArray(def.tiles)) {
    for (const t of def.tiles) {
      if (!t || typeof t !== 'object') continue;
      if (t.from_status !== undefined) {
        if (t.from_status !== true) F.fail(`${path}: tile "${t.label}" has a "from_status" that is not true.`);
        else if (def.status === undefined) F.fail(`${path}: tile "${t.label}" has "from_status" but metric.yml has no "status" block.`);
        if (t.text !== undefined || t.series !== undefined) F.fail(`${path}: tile "${t.label}" has "from_status" and also "text" or "series". A status tile shows only the status word and its sub_text.`);
      }
    }
  }
  if (def.table !== undefined && def.table !== null && (Array.isArray(def.table) ? def.table.length === 0 || def.table.some((t) => !t || typeof t !== 'object' || Array.isArray(t)) : typeof def.table !== 'object')) {
    F.fail(`${path}: "table" must be one table or a list of tables (each with period_header and columns).`);
  }
  for (const t of tablesOf(def)) {
    if (!Array.isArray(t.columns) || t.columns.length === 0) F.fail(`${path}: a table has no "columns".`);
  }
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
    // a value is a number or one of the source's codes (.., na, np, -), which has no numeric value
    const isCode = isValueCode(valueText);
    const value = isCode ? NaN : /^-?\d+(\.\d+)?$/.test(valueText) ? Number(valueText) : NaN;
    if (!isCode && !Number.isFinite(value)) { F.fail(`${where}: the value "${valueText}" is not a number or one of the codes .., na, np, -.`); good = false; }
    if (!STATUSES.includes(status)) { F.fail(`${where}: the status "${status}" is not one of ${STATUSES.join(', ')}.`); good = false; }
    if (!KNOWN_UNITS.includes(unit)) { F.fail(`${where}: the unit "${unit}" is not one the site can format (${KNOWN_UNITS.join(', ')}).`); good = false; }
    if (good) {
      const key = `${date}|${series}|${jurisdiction}`;
      if (seen.has(key)) {
        F.fail(`${where}: duplicate of line ${seen.get(key)}. Each date, series and jurisdiction may appear once.`);
        good = false;
      } else seen.set(key, line);
    }
    if (good) rows.push({ line, date, period, series, jurisdiction, value, valueText, unit, status, isCode });
  });
  return { rows, sha };
}

// The full tables of a metric: `table` is one table, or a list of tables (each shown in turn under "All figures as a table").
function tablesOf(def) {
  if (Array.isArray(def.table)) return def.table.filter((t) => t && typeof t === 'object');
  return def.table && typeof def.table === 'object' ? [def.table] : [];
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
  for (const t of tablesOf(def)) for (const c of t.columns ?? []) add(c?.series, 'the table');
  return used;
}

// Every place a series is picked, with the jurisdiction asked for (if any). A series that has figures
// for more than one jurisdiction must be picked with `jurisdiction:` so the page cannot mix them up.
function selectionsInDefinition(def) {
  const out = [];
  const add = (id, jurisdiction, where) => { if (typeof id === 'string') out.push({ id, jurisdiction, where }); };
  if (Array.isArray(def.views)) for (const v of def.views) for (const l of v?.lines ?? []) add(l?.series, l?.jurisdiction, `view "${v.id}"`);
  if (Array.isArray(def.tiles)) {
    for (const t of def.tiles) { add(t?.series, t?.jurisdiction, `tile "${t.label}"`); add(t?.sub?.series, t?.sub?.jurisdiction, `tile "${t.label}"`); }
  }
  for (const t of tablesOf(def)) for (const c of t.columns ?? []) add(c?.series, c?.jurisdiction, 'the table');
  return out;
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

// 6a. every series declares how far an accepted figure may be revised
function revisionProblem(rev) {
  if (rev === undefined || rev === null) {
    return 'has no "revision" tolerance. Add for example "revision: {max_abs: 500, max_pct: 1, pct_floor: 5000}" (max_pct and pct_floor are optional). See metrics/README.md.';
  }
  if (typeof rev !== 'object' || Array.isArray(rev)) return 'has a "revision" that is not a set of fields. Use for example "revision: {max_abs: 0.5}".';
  for (const k of Object.keys(rev)) {
    if (!REVISION_KEYS.includes(k)) return `has a "revision" field "${k}" that the checker does not know. Known: ${REVISION_KEYS.join(', ')}.`;
  }
  if (!isNum(rev.max_abs) || rev.max_abs <= 0) return 'needs "revision" to have "max_abs", a number above zero.';
  if (rev.max_pct !== undefined && (!isNum(rev.max_pct) || rev.max_pct <= 0)) return 'has a "revision" "max_pct" that is not a number above zero.';
  if (rev.pct_floor !== undefined && (!isNum(rev.pct_floor) || rev.pct_floor < 0)) return 'has a "revision" "pct_floor" that is not a number of zero or more.';
  return null;
}

// Does changing a figure from `a` to `b` break the tolerance `rev`? Returns a reason or null.
function revisionBreach(a, b, rev) {
  const change = Number(Math.abs(b - a).toPrecision(12)); // 94.51 - 94.5 is 0.0100000000000051 in floating point; it is 0.01

  if (change === 0) return null;
  // A change of sign between two sizeable figures fails whatever its size.
  const signLimit = rev.pct_floor !== undefined ? rev.pct_floor : rev.max_abs;
  if (a * b < 0 && Math.abs(a) >= signLimit && Math.abs(b) >= signLimit) return 'the sign has changed';
  if (change <= rev.max_abs) return null;
  if (rev.max_pct === undefined) return `the change is more than ${rev.max_abs}`;
  const floor = rev.pct_floor === undefined ? 0 : rev.pct_floor;
  if (Math.abs(a) < floor) return `the change is more than ${rev.max_abs}`;
  const pct = Math.abs(a) === 0 ? Infinity : (change / Math.abs(a)) * 100;
  if (pct > rev.max_pct) return `the change is more than ${rev.max_abs} and more than ${rev.max_pct} per cent`;
  return null;
}

const tidy = (n) => String(Number(n.toPrecision(12)));
const signed = (n) => (n > 0 ? '+' : n < 0 ? '-' : '') + tidy(Math.abs(n));

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
  const isDerived = (s) => s !== undefined && s.derive !== undefined;

  // 3a. a derived series (metric.yml `derive`) is worked out here, from stored or other derived series, the
  // same way the page works it out (src/lib/derive.mjs). It is never in data.csv. A date where an input is
  // missing, unknown (na, np) or a code that cannot be used has no derived figure (left out, not guessed).
  const derivedDefs = [...declared.values()].filter(isDerived);
  let derivedGroups = new Map(); // "id|jurisdiction" -> rows, oldest first
  let derivedOk = true;
  for (const s of derivedDefs) {
    const problems = deriveProblems(s.id, s.derive, (x) => declared.get(x)?.frequency, s.frequency);
    for (const m of problems) F.fail(`${yml}: ${m}`);
    if (problems.length > 0) derivedOk = false;
    for (const src of deriveInputs(s.derive)) {
      if (!declared.has(src)) { F.fail(`${yml}: series "${s.id}" is worked out from "${src}", which is not in the "series" list.`); derivedOk = false; }
      else if (!isDerived(declared.get(src)) && !inData.has(src)) { F.fail(`${yml}: series "${s.id}" is worked out from "${src}", which has no rows in data.csv.`); derivedOk = false; }
    }
    if (inData.has(s.id)) F.fail(`${path}: series "${s.id}" is derived in metric.yml, so it must not have rows in data.csv. Derived figures are worked out when the site is built.`);
    if (s.frequency === undefined) F.fail(`${yml}: series "${s.id}" has no "frequency". Add one of: ${Object.keys(FREQUENCIES).join(', ')}.`);
  }
  if (derivedOk && derivedDefs.length > 0) {
    const stored = new Map([...groups].map(([k, g]) => [k, g.map((r) => ({ date: r.date, period: r.period, valueText: r.valueText, unit: r.unit, line: r.line }))]));
    const out = computeDerived([...declared.values()], stored);
    for (const m of out.problems) F.fail(`${yml}: ${m}`);
    const lineOf = new Map([...groups].map(([k, g]) => [k, new Map(g.map((r) => [r.date, r.line]))]));
    derivedGroups = new Map([...out.groups].map(([k, rows]) => [k, rows.map((r) => ({ ...r, line: undefined, series: k.split('|')[0], jurisdiction: k.slice(k.indexOf('|') + 1) }))]));
    void lineOf;
  }

  // 4. series match in both directions
  for (const [id, where] of seriesNamedInViews(def)) {
    if (!inData.has(id) && !isDerived(declared.get(id))) F.fail(`${yml}: ${where} uses series "${id}", which has no rows in data.csv.`);
    if (!declared.has(id)) F.fail(`${yml}: ${where} uses series "${id}", which is not in the "series" list.`);
  }
  for (const id of inData) {
    if (!declared.has(id)) F.fail(`${path}: series "${id}" is in data.csv but is not declared in the "series" list in metric.yml.`);
  }
  for (const [id, s] of declared) {
    if (!inData.has(id) && !isDerived(s)) F.fail(`${yml}: series "${id}" is declared but has no rows in data.csv.`);
  }
  // 4a. a series with figures for several jurisdictions must be picked with "jurisdiction:", and the one
  // named must have figures
  const jurisdictionsOf = (id) => new Set([...groups.keys(), ...derivedGroups.keys()].filter((k) => k.startsWith(`${id}|`)).map((k) => k.slice(id.length + 1)));
  for (const { id, jurisdiction, where } of selectionsInDefinition(def)) {
    const have = jurisdictionsOf(id);
    if (have.size === 0) continue; // reported above
    if (jurisdiction === undefined) {
      if (have.size > 1) F.fail(`${yml}: ${where} uses series "${id}", which has figures for ${have.size} jurisdictions (${[...have].sort().join(', ')}). Name one with "jurisdiction:".`);
    } else if (!have.has(jurisdiction)) {
      F.fail(`${yml}: ${where} asks for series "${id}" in the jurisdiction "${jurisdiction}", which has no figures. It has: ${[...have].sort().join(', ')}.`);
    }
  }

  for (const [id, s] of declared) {
    if (!isDerived(s)) {
      const problem = revisionProblem(s.revision);
      if (problem) F.fail(`${yml}: series "${id}" ${problem}`);
    }
    if (!inData.has(id) && !isDerived(s)) continue;
    const seriesGroups = isDerived(s)
      ? [...derivedGroups.entries()].filter(([k]) => k.startsWith(`${id}|`)).map(([, g]) => g)
      : [...groups.entries()].filter(([k]) => k.startsWith(`${id}|`)).map(([, g]) => g);
    // rows holding a code (.., na, np, -) are dates with no figure: they keep their place in the schedule
    // but have no value to range-check
    const numericGroups = seriesGroups.map((g) => g.filter((r) => !r.isCode));

    // 4b. `decimals` is a display setting (the places shown for a per cent or a rate). It must be a whole number
    // from 0 to 3, and no stored figure may have more places than it shows, so the page never hides part of a figure.
    if (s.decimals !== undefined) {
      if (!Number.isInteger(s.decimals) || s.decimals < 0 || s.decimals > 3) F.fail(`${yml}: series "${id}" has a "decimals" that is not a whole number from 0 to 3.`);
      else if (!isDerived(s)) {
        let reported = 0;
        for (const r of numericGroups.flat()) {
          const places = r.valueText.includes('.') ? r.valueText.split('.')[1].length : 0;
          if (places > s.decimals && ++reported <= 10) F.fail(`${path}: line ${r.line}, ${id} (${r.jurisdiction}) on ${r.date} is ${r.valueText}, which has more decimal places than the ${s.decimals} the page shows for this series ("decimals" in metric.yml).`);
        }
      }
    }

    // 5. frequency and gaps (a derived series takes its dates from the stored series, which is checked itself)
    const freq = FREQUENCIES[s.frequency];
    if (isDerived(s)) { /* its frequency is checked in 3a; its dates come from the stored series */ }
    else if (s.frequency === undefined) F.fail(`${yml}: series "${id}" has no "frequency". Add one of: ${Object.keys(FREQUENCIES).join(', ')}.`);
    else if (!freq) F.fail(`${yml}: series "${id}" has frequency "${s.frequency}", which the validator does not know. Known: ${Object.keys(FREQUENCIES).join(', ')}.`);
    else {
      for (const g of seriesGroups) {
        let reported = 0;
        if (freq.onSchedule) {
          for (const r of g) {
            if (!freq.onSchedule(r.date)) F.fail(`${path}: line ${r.line}, ${id} (${r.jurisdiction}) on ${r.date} is not ${freq.scheduleHint}, as ${s.frequency} data must be.`);
          }
        }
        for (let i = 1; i < g.length; i++) {
          const a = g[i - 1].date;
          const b = g[i].date;
          let exp = freq.next(a);
          const missing = [];
          let steps = 0;
          // a frequency with `toleranceDays` accepts a date that many days either side of the expected one
          const hit = (e) => e === b || (freq.toleranceDays !== undefined && Math.abs(daysBetween(e, b)) <= freq.toleranceDays);
          while (exp < b && !hit(exp) && steps++ < 2000) { missing.push(exp); exp = freq.next(exp); }
          if (hit(exp) && missing.length === 0) continue;
          if (++reported > 10) break;
          if (hit(exp)) F.fail(`${path}: ${id} (${g[0].jurisdiction}) is missing ${missing.join(', ')}; the rows jump from ${a} to ${b}.`);
          else F.fail(`${path}: ${id} (${g[0].jurisdiction}) has a row on ${b} (line ${g[i].line}) which is not on the ${s.frequency} schedule after ${a}; expected ${freq.next(a)}.`);
        }
      }
    }

    // 5a. one unit for the whole series (every jurisdiction), so the page never mixes units on one line
    if (!isDerived(s)) {
      const units = [...new Set(seriesGroups.flat().map((r) => r.unit))];
      if (units.length > 1) F.fail(`${path}: series "${id}" has more than one unit (${units.join(', ')}).`);
    }

    // 6. plausible range, and the optional step limit
    const p = s.plausible;
    const hasRange = p && typeof p === 'object' && isNum(p.min) && isNum(p.max) && p.min <= p.max;
    if (!hasRange) F.fail(`${yml}: series "${id}" needs "plausible" with a numeric min and max (min not above max).`);
    else {
      for (const g of numericGroups) {
        for (const r of g) {
          if (r.value < p.min || r.value > p.max) {
            F.fail(r.derivedFrom
              ? `${yml}: ${id} (${r.jurisdiction}) on ${r.date}, worked out from ${r.derivedFrom}, is ${r.value}, outside the plausible range ${p.min} to ${p.max} set in metric.yml.`
              : `${path}: line ${r.line}, ${id} (${r.jurisdiction}) on ${r.date} is ${r.value}, outside the plausible range ${p.min} to ${p.max} set in metric.yml.`);
          }
        }
      }
    }
    if (s.max_step_pct !== undefined) {
      const floor = s.max_step_floor === undefined ? 0 : s.max_step_floor;
      if (!isNum(s.max_step_pct) || s.max_step_pct <= 0) F.fail(`${yml}: series "${id}" has a "max_step_pct" that is not a positive number.`);
      else if (!isNum(floor) || floor < 0) F.fail(`${yml}: series "${id}" has a "max_step_floor" that is not a number of zero or more.`);
      else {
        for (const g of numericGroups) {
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
  return derivedGroups;
}

// 6b. a series that is a copy of another metric's series must equal it, row for row.
// metric.yml: copy_of: {metric: inflation, series: headline_quarterly}. Every row of the copy must
// have a row in the other metric's data.csv with the same date, series and jurisdiction, and the
// same value and unit. (The other metric reports its own problems; here only its rows are read.)
function checkCopies(root, slug, def, data, F) {
  const yml = `metrics/${slug}/metric.yml`;
  const path = `metrics/${slug}/data.csv`;
  const others = new Map(); // metric slug -> Map("date|series|jurisdiction" -> row), or null if unreadable
  for (const s of Array.isArray(def.series) ? def.series : []) {
    if (!s || s.copy_of === undefined) continue;
    const c = s.copy_of;
    if (!c || typeof c !== 'object' || Array.isArray(c) || typeof c.metric !== 'string' || typeof c.series !== 'string'
        || Object.keys(c).some((k) => k !== 'metric' && k !== 'series') || !/^[a-z0-9-]+$/.test(c.metric) || c.metric === slug) {
      F.fail(`${yml}: series "${s.id}" has a "copy_of" that is not {metric: <another metric's folder name>, series: <its series id>}.`);
      continue;
    }
    const otherPath = `metrics/${c.metric}/data.csv`;
    if (!others.has(c.metric)) {
      const full = join(root, otherPath);
      if (!existsSync(full)) others.set(c.metric, null);
      else {
        const rows = loadDataCsv(root, c.metric, { fail: () => {}, warn: () => {} })?.rows ?? [];
        others.set(c.metric, new Map(rows.map((r) => [`${r.date}|${r.series}|${r.jurisdiction}`, r])));
      }
    }
    const other = others.get(c.metric);
    if (!other) {
      F.fail(`${yml}: series "${s.id}" is a copy of ${c.metric} (${c.series}), but ${otherPath} is missing.`);
      continue;
    }
    if (![...other.values()].some((r) => r.series === c.series)) {
      F.fail(`${yml}: series "${s.id}" is a copy of ${c.series} in ${c.metric}, but ${otherPath} has no rows for that series.`);
      continue;
    }
    let reported = 0;
    for (const r of data.rows.filter((x) => x.series === s.id)) {
      const o = other.get(`${r.date}|${c.series}|${r.jurisdiction}`);
      let problem = null;
      if (!o) problem = `${otherPath} has no ${c.series} row for ${r.date}`;
      else if (o.value !== r.value) problem = `the ${c.metric} page's ${c.series} for that date is ${o.valueText}`;
      else if (o.unit !== r.unit) problem = `the ${c.metric} page's ${c.series} for that date is in ${o.unit}`;
      if (!problem) continue;
      if (++reported > 10) { F.fail(`${path}: more rows of ${s.id} differ from ${c.metric} (${c.series}); only the first 10 are listed.`); break; }
      F.fail(`${path}: line ${r.line}, ${s.id} (${r.jurisdiction}) on ${r.date} is ${r.valueText} (${r.unit}), but ${problem}. ${s.id} must equal ${c.series} on the ${c.metric} page (copy_of in metric.yml).`);
    }
  }
}

// 6c. the state and territory panel. `state_panel: true` needs a `state_panel_config` in metric.yml:
//   series (a stored series), national (the jurisdiction drawn as the grey reference line) and
//   national_label (its name in the read-out), heading, note, headers (the three column headings of the
//   table of latest figures), and places: the eight jurisdictions in the fixed order NSW, Vic, Qld, WA, SA, Tas, ACT, NT, each with
//   jurisdiction (full name as in data.csv), abbreviation and name (the place shown, such as the capital city).
function checkStatePanel(slug, def, data, derivedGroups, F) {
  const yml = `metrics/${slug}/metric.yml`;
  if (def.state_panel !== undefined && typeof def.state_panel !== 'boolean') F.fail(`${yml}: "state_panel" must be true or false.`);
  if (def.state_panel !== true) return;
  const c = def.state_panel_config;
  if (!c || typeof c !== 'object' || Array.isArray(c)) {
    F.fail(`${yml}: "state_panel" is true but there is no "state_panel_config" (series, national, heading, note and places).`);
    return;
  }
  for (const k of Object.keys(c)) {
    if (!['series', 'national', 'national_label', 'heading', 'note', 'headers', 'places', 'date_format', 'extra_columns', 'y_range', 'markers'].includes(k)) F.fail(`${yml}: "state_panel_config" has a field "${k}" that the checker does not know.`);
  }
  for (const k of ['series', 'national', 'national_label', 'heading', 'note']) {
    if (typeof c[k] !== 'string' || c[k].trim() === '') F.fail(`${yml}: "state_panel_config" needs "${k}", as text.`);
  }
  if (!Array.isArray(c.headers) || c.headers.length !== 3 || c.headers.some((h) => typeof h !== 'string' || h.trim() === '')) {
    F.fail(`${yml}: "state_panel_config" needs "headers", a list of three column headings (place, month, figure).`);
  }
  const places = Array.isArray(c.places) ? c.places : null;
  if (!places) { F.fail(`${yml}: "state_panel_config" needs "places", a list of the eight jurisdictions.`); return; }
  if (places.length !== STATE_ORDER.length) F.fail(`${yml}: the state panel must list exactly ${STATE_ORDER.length} places in the fixed order (${STATE_ORDER.map((x) => x.abbreviation).join(', ')}); it lists ${places.length}.`);
  STATE_ORDER.forEach((want, i) => {
    const got = places[i];
    if (!got || typeof got !== 'object') return;
    if (got.jurisdiction !== want.jurisdiction) F.fail(`${yml}: state panel place ${i + 1} is "${got.jurisdiction}" but must be "${want.jurisdiction}": the order is fixed (${STATE_ORDER.map((x) => x.abbreviation).join(', ')}).`);
    if (got.abbreviation !== want.abbreviation) F.fail(`${yml}: state panel place ${i + 1} (${want.jurisdiction}) has the abbreviation "${got.abbreviation}" but must have "${want.abbreviation}".`);
    if (typeof got.name !== 'string' || got.name.trim() === '') F.fail(`${yml}: state panel place ${i + 1} (${want.jurisdiction}) has no "name" (the place shown, such as the capital city).`);
  });
  if (typeof c.series !== 'string') return;
  if (c.date_format !== undefined && !['period', 'month_year'].includes(c.date_format)) F.fail(`${yml}: "state_panel_config" has a "date_format" that is not period or month_year.`);
  const declaredIds = new Set((Array.isArray(def.series) ? def.series : []).map((x) => x?.id));
  if (c.extra_columns !== undefined) {
    if (!Array.isArray(c.extra_columns) || c.extra_columns.some((x) => !x || typeof x.header !== 'string' || x.header.trim() === '' || typeof x.series !== 'string' || !declaredIds.has(x.series) || (x.after !== undefined && typeof x.after !== 'boolean') || (x.own_latest !== undefined && typeof x.own_latest !== 'boolean') || (x.with_period !== undefined && typeof x.with_period !== 'boolean') || (x.with_period === true && x.own_latest !== true) || Object.keys(x).some((k) => !['header', 'series', 'after', 'own_latest', 'with_period'].includes(k)))) {
      F.fail(`${yml}: "state_panel_config" has "extra_columns" that is not a list of {header, series} (and optionally after: true, own_latest: true, and with_period: true, which needs own_latest) with a series from the "series" list.`);
    }
  }
  if (c.markers !== undefined && typeof c.markers !== 'boolean') F.fail(`${yml}: "state_panel_config" has a "markers" that is not true or false.`);
  if (c.y_range !== undefined) {
    const r = c.y_range;
    if (!r || typeof r !== 'object' || Array.isArray(r) || Object.keys(r).some((k) => k !== 'min' && k !== 'max') || !isNum(r.min) || !isNum(r.max) || r.min >= r.max) {
      F.fail(`${yml}: "state_panel_config" has a "y_range" that is not {min: <number>, max: <larger number>}.`);
    }
  }
  // the series is stored (rows in data.csv) or derived (worked out, same code as the page)
  const rowsFor = (j) => [...data.rows.filter((r) => r.series === c.series && r.jurisdiction === j && !r.isCode), ...(derivedGroups.get(`${c.series}|${j}`) ?? [])];
  if (!declaredIds.has(c.series)) {
    F.fail(`${yml}: the state panel series "${c.series}" must be in the "series" list.`);
    return;
  }
  const latest = new Map();
  for (const j of [c.national, ...places.map((x) => x?.jurisdiction)]) {
    if (typeof j !== 'string') continue;
    const rows = rowsFor(j);
    if (rows.length === 0) F.fail(`${yml}: the state panel needs ${c.series} for "${j}", but data.csv has no rows for it.`);
    else latest.set(j, rows.map((r) => r.date).sort().at(-1));
    const yr = c.y_range;
    if (yr && isNum(yr.min) && isNum(yr.max) && yr.min < yr.max) {
      const out = rows.find((r) => r.value < yr.min || r.value > yr.max);
      if (out) F.fail(`${yml}: the state panel scale is fixed at ${yr.min} to ${yr.max} ("y_range"), but ${c.series} for "${j}" on ${out.date} is ${out.value}, outside it.`);
    }
  }
  const states = places.map((x) => x?.jurisdiction).filter((j) => latest.has(j));
  const ends = new Set(states.map((j) => latest.get(j)));
  // an extra column with own_latest shows that series' own latest figure for each place, so every place needs one
  for (const x of Array.isArray(c.extra_columns) ? c.extra_columns : []) {
    if (!x || x.own_latest !== true || typeof x.series !== 'string' || !declaredIds.has(x.series)) continue;
    for (const j of places.map((p) => p?.jurisdiction).filter((j) => typeof j === 'string')) {
      const has = [...data.rows.filter((r) => r.series === x.series && r.jurisdiction === j && !r.isCode), ...(derivedGroups.get(`${x.series}|${j}`) ?? [])];
      if (has.length === 0) F.fail(`${yml}: the state panel column "${x.header}" shows the latest ${x.series} for each place, but "${j}" has no figure for it.`);
    }
  }
  if (ends.size > 1) F.fail(`${yml}: the places in the state panel do not all end on the same date (${[...ends].sort().join(', ')}), so the table of latest figures would mix months.`);
}

// 7. rows never fall, and accepted figures are not revised by more than their tolerance
function lockFromGroups(groups, sha) {
  const series = [...groups.values()]
    .map((g) => ({
      series: g[0].series,
      jurisdiction: g[0].jurisdiction,
      rows: g.length,
      first: g[0].date,
      last: g.at(-1).date,
      values: Object.fromEntries(g.map((r) => [r.date, r.valueText])),
    }))
    .sort((a, b) => (a.series < b.series ? -1 : a.series > b.series ? 1 : a.jurisdiction < b.jurisdiction ? -1 : 1));
  return { lock_version: LOCK_VERSION, data_sha256: sha, series };
}

function checkLock(root, slug, def, groups, sha, F) {
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

  // The lock must hold every accepted value (version 2).
  if (lock.lock_version === undefined || lock.lock_version < LOCK_VERSION || lock.series.some((l) => !l || typeof l.values !== 'object' || l.values === null)) {
    F.fail(`${path}: the lock file is in the old format, which does not record the accepted values, so past figures cannot be protected. Run "npm run accept-data" once to upgrade it.`, 'lock-old');
    return;
  }
  if (lock.lock_version > LOCK_VERSION) {
    F.fail(`${path}: the lock file is version ${lock.lock_version}, newer than this checker understands (version ${LOCK_VERSION}).`);
    return;
  }

  // Revisions to figures that were accepted before.
  let revised = 0;
  const csvPath = `metrics/${slug}/data.csv`;
  const tolerance = new Map((def && Array.isArray(def.series) ? def.series : []).filter((s) => s && typeof s.id === 'string').map((s) => [s.id, s.revision]));
  for (const l of lock.series) {
    const g = groups.get(`${l.series}|${l.jurisdiction}`);
    if (!g) continue;
    const rev = tolerance.get(l.series);
    const usable = revisionProblem(rev) === null; // a missing or bad "revision" is reported in checkSeries
    for (const r of g) {
      if (!Object.hasOwn(l.values, r.date)) continue; // a new date is not a revision
      const oldText = String(l.values[r.date]);
      if (oldText === r.valueText) continue;
      const a = Number(oldText);
      // a figure that becomes a code, or a code that becomes a figure (or another code), is always a revision to check
      const codeChange = isValueCode(oldText) || r.isCode;
      if (!codeChange && (!Number.isFinite(a) || a === r.value)) continue;
      const why = codeChange ? `a figure or code changed between "${oldText}" and "${r.valueText}"` : usable ? revisionBreach(a, r.value, rev) : null;
      if (!why) revised++;
      if (why) {
        const short = codeChange ? `${csvPath}: ${l.series} (${l.jurisdiction}) on ${r.date} (${r.period}) was ${oldText} when last accepted and is now ${r.valueText} (${why})` : `${csvPath}: ${l.series} (${l.jurisdiction}) on ${r.date} (${r.period}) was ${oldText} when last accepted and is now ${r.valueText}, a change of ${signed(r.value - a)} (${why})`;
        F.fail(`${short}. ${REVISION_HINT}`, 'revision', { short });
      }
    }
  }
  if (bad === 0 && lock.data_sha256 !== sha) {
    F.warn(`metrics/${slug}/data.csv: data has changed since it was last accepted${revised ? ` (${revised} accepted figure${revised === 1 ? '' : 's'} revised, within the allowed tolerance)` : ''}. If the changes are expected, check them against the source and run "npm run accept-data".`);
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
    // An entry with a "path" is a reference to a file elsewhere in the project (a series copied from
    // another metric, with the file's checksum at the time of copying). It is not a file in this
    // folder, and the other file may legitimately change later, so only its shape is checked.
    if (info && typeof info === 'object' && info.path !== undefined) {
      const okPath = typeof info.path === 'string' && /^metrics\/[a-z0-9-]+\/[A-Za-z0-9._-]+$/.test(info.path);
      if (!okPath) F.fail(`${manifestRel}: the entry for "${name}" has a "path" that is not a file inside a metrics folder.`);
      else if (typeof info.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(info.sha256) || !isNum(info.bytes)) F.fail(`${manifestRel}: the entry for "${name}" has no valid sha256 and bytes.`);
      continue;
    }
    // An entry with "editions" is a note kept by a scraper that merges editions: for each stored period (a year),
    // the edition of the source it last came from. It is not a file, so only its shape is checked.
    if (info && typeof info === 'object' && info.editions !== undefined) {
      const e = info.editions;
      const okMap = e && typeof e === 'object' && !Array.isArray(e) && Object.keys(e).length > 0 && Object.values(e).every((v) => typeof v === 'string' && v !== '');
      if (!okMap) F.fail(`${manifestRel}: the entry for "${name}" has "editions" that is not a non-empty map of period to edition.`);
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
  const derivedGroupsOf = new Map(); // slug -> worked-out series (for the state panel check)

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
      if (def) derivedGroupsOf.set(slug, checkSeries(slug, def, data, groups, F));
      if (def) checkCopies(root, slug, def, data, F);
      if (def) checkStatePanel(slug, def, data, derivedGroupsOf.get(slug) ?? new Map(), F);
      checkLock(root, slug, def, groups, data.sha, F);
      locks.set(slug, lockFromGroups(groups, data.sha));

      // 10. every date used by an inflation-adjusted view has a price index
      if (def) {
        const realSeries = new Set();
        for (const v of Array.isArray(def.views) ? def.views : []) {
          if (v?.derive === 'real') for (const l of v.lines ?? []) realSeries.add(l.series);
        }
        for (const t of tablesOf(def)) for (const c of t.columns ?? []) if (c?.derive === 'real') realSeries.add(c.series);
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
  let acceptRevisions = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--root') {
      if (!argv[i + 1]) { console.error('--root needs a folder.'); return 2; }
      root = resolve(argv[++i]);
    } else if (argv[i] === '--accept') accept = true;
    else if (argv[i] === '--accept-revisions') { accept = true; acceptRevisions = true; }
    else { console.error(`Unknown option ${argv[i]}. Use --root <folder>, --accept or --accept-revisions.`); return 2; }
  }

  const r = validateRoot(root);
  // When accepting, a missing or old-format lock file is not a problem: writing it is the point.
  // Large revisions stop being a problem only when --accept-revisions is given. Nothing else is excused.
  const excused = (f) => accept && (f.kind === 'lock-missing' || f.kind === 'lock-old' || (acceptRevisions && f.kind === 'revision'));
  const blocking = r.fails.filter((f) => !excused(f));

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
    for (const f of r.fails.filter((x) => x.kind === 'revision')) console.log(`ACCEPTED REVISION: ${f.short}.`);
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
