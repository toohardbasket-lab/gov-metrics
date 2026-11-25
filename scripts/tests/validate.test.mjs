#!/usr/bin/env node
// Tests for scripts/validate.mjs. No test framework: run with  npm run test:validate
//
// The tests copy metrics/ and shared/ (and src/lib/format.ts) into a temporary folder,
// confirm the clean copy passes, then damage the copy in one way at a time, run the
// validator against it with --root, and check that it fails with a message naming the problem.

import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { computeDerived, deriveProblems, deriveYearEndedChange, isPeriodEnd, isRealIsoDate, isValueCode, periodLabel, periodsBetween, ratioText, shiftPeriods, sumText, yearEndedChangeText } from '../../src/lib/derive.mjs';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const VALIDATE = join(REPO, 'scripts', 'validate.mjs');
const SLUG = 'commonwealth-debt';

const base = mkdtempSync(join(tmpdir(), 'validate-test-'));
const pristine = join(base, 'pristine');
const work = join(base, 'work');
mkdirSync(pristine);
cpSync(join(REPO, 'metrics'), join(pristine, 'metrics'), { recursive: true });
cpSync(join(REPO, 'shared'), join(pristine, 'shared'), { recursive: true });
mkdirSync(join(pristine, 'src', 'lib'), { recursive: true });
cpSync(join(REPO, 'src', 'lib', 'format.ts'), join(pristine, 'src', 'lib', 'format.ts'));

function fresh() {
  rmSync(work, { recursive: true, force: true });
  cpSync(pristine, work, { recursive: true });
}
const run = (...args) => {
  const r = spawnSync(process.execPath, [VALIDATE, '--root', work, ...args], { encoding: 'utf8' });
  return { code: r.status, out: (r.stdout ?? '') + (r.stderr ?? '') };
};
const p = (...parts) => join(work, ...parts);
const UN = 'unemployment-rate';
const dataPath = (slug = SLUG) => p('metrics', slug, 'data.csv');
const readText = (f) => readFileSync(f, 'utf8');
const sha = (f) => createHash('sha256').update(readFileSync(f)).digest('hex');

// Edit data.csv line by line. `fn(line)` returns the new line, an array of lines, or null to delete.
function editRows(match, fn, slug = SLUG) {
  const lines = readText(dataPath(slug)).split('\n');
  const out = [];
  let hit = 0;
  for (const line of lines) {
    if (match(line)) {
      hit++;
      const r = fn(line);
      if (r === null) continue;
      if (Array.isArray(r)) out.push(...r);
      else out.push(r);
    } else out.push(line);
  }
  if (hit === 0) throw new Error('test set-up: no row matched');
  writeFileSync(dataPath(slug), out.join('\n'));
}
const row = (date, series) => (l) => l.startsWith(`${date},`) && l.includes(`,${series},`);
const setValue = (line, v) => { const c = line.split(','); c[4] = v; return c.join(','); };
function editFile(file, fn) {
  const before = readText(file);
  const after = fn(before);
  if (after === before) throw new Error('test set-up: the edit changed nothing');
  writeFileSync(file, after);
}

let passed = 0;
let failed = 0;
const failures = [];
const names = [];

function check(name, cond, detail) {
  if (cond) return true;
  failures.push(`${name}: ${detail}`);
  return false;
}

// A case damages a fresh copy, then must fail with output matching `expect` (a regular expression).
function failCase(name, damage, expect) {
  names.push(name);
  fresh();
  damage();
  const r = run();
  const ok =
    check(name, r.code !== 0, `expected a non-zero exit but got ${r.code}`) &&
    check(name, expect.test(r.out), `output did not match ${expect}.\n${r.out}`);
  if (ok) { passed++; console.log(`  ok   ${name}`); } else { failed++; console.log(`  FAIL ${name}`); }
}

function plainCase(name, body) {
  names.push(name);
  fresh();
  let ok = false;
  try { ok = body(); } catch (e) { failures.push(`${name}: threw ${e.message}`); }
  if (ok) { passed++; console.log(`  ok   ${name}`); } else { failed++; console.log(`  FAIL ${name}`); }
}

console.log('validate.mjs tests');

plainCase('the clean copy passes', () => {
  const r = run();
  return check('the clean copy passes', r.code === 0 && /Validation passed/.test(r.out) && !/WARNING/.test(r.out), `exit ${r.code}\n${r.out}`);
});

// ---- data.csv
failCase('delete a middle year of one series', () => editRows(row('2000-06-30', 'net_debt'), () => null), /net_debt \(Commonwealth\) is missing 2000-06-30/);
failCase('change a value to text', () => editRows(row('1990-06-30', 'gross_debt'), (l) => setValue(l, 'abc')), /line \d+, gross_debt \(Commonwealth\) on 1990-06-30: the value "abc" is not a number/);
failCase('put a value outside its range', () => editRows(row('2000-06-30', 'gross_debt_pct_gdp'), (l) => setValue(l, '150')), /gross_debt_pct_gdp \(Commonwealth\) on 2000-06-30 is 150, outside the plausible range 0 to 100/);
failCase('flip the sign of a net debt figure', () => editRows(row('2026-06-30', 'net_debt'), (l) => setValue(l, '-' + l.split(',')[4])), /net_debt \(Commonwealth\) on 2026-06-30 is -549969, outside the plausible range -200000 to 3000000/);
failCase('duplicate a row', () => editRows(row('1995-06-30', 'net_debt'), (l) => [l, l]), /net_debt \(Commonwealth\) on 1995-06-30: duplicate of line \d+/);
failCase('remove the last year (rows fall against the lock)', () => editRows((l) => l.startsWith('2026-06-30,'), () => null), /data\.lock\.json: gross_debt \(Commonwealth\) has 55 rows, fewer than the 56/);
failCase('rename a series in data.csv', () => editFile(dataPath(), (t) => t.replaceAll(',net_debt,', ',net_debt_renamed,')), /series "net_debt_renamed" is in data\.csv but is not declared/);
failCase('set an unknown status', () => editRows(row('1980-06-30', 'gross_debt'), (l) => { const c = l.split(','); c[6] = 'provisional'; return c.join(','); }), /on 1980-06-30: the status "provisional" is not one of actual, estimate, forecast/);
failCase('use a date that is not real', () => editRows(row('1980-06-30', 'gross_debt'), (l) => l.replace('1980-06-30', '1980-06-31')), /"1980-06-31" is not a real date/);
failCase('use an unknown unit', () => editRows(row('1980-06-30', 'gross_debt'), (l) => { const c = l.split(','); c[5] = 'furlongs'; return c.join(','); }), /the unit "furlongs" is not one the site can format/);
failCase('put a quote mark in data.csv', () => editRows(row('1980-06-30', 'gross_debt'), (l) => l.replace('1979-80', '"1979-80"')), /contains a quote character/);
failCase('give a row the wrong number of fields', () => editRows(row('1980-06-30', 'gross_debt'), (l) => l + ',extra'), /has 8 fields but must have 7/);
failCase('change the header', () => editFile(dataPath(), (t) => t.replace('date,period,series', 'date,series,period')), /the header is .* but must be exactly/);
failCase('delete data.csv', () => rmSync(dataPath()), /data\.csv: the file is missing/);

// ---- monthly data (the unemployment rate) and the pct unit
const unRow = (date) => (l) => l.startsWith(`${date},`);
const un = (match, fn) => editRows(match, fn, UN);
failCase('monthly: delete a middle month', () => un(unRow('2000-06-30'), () => null), /unemployment_rate \(Australia\) is missing 2000-06-30; the rows jump from 2000-05-31 to 2000-07-31/);
failCase('monthly: delete two months in a row', () => un((l) => l.startsWith('2005-03-31,') || l.startsWith('2005-04-30,'), () => null), /is missing 2005-03-31, 2005-04-30/);
failCase('monthly: delete a leap-day February', () => un(unRow('2000-02-29'), () => null), /is missing 2000-02-29; the rows jump from 2000-01-31 to 2000-03-31/);
failCase('monthly: a leap-year February dated the 28th is off schedule', () => un(unRow('2000-02-29'), (l) => l.replace('2000-02-29', '2000-02-28')), /2000-02-28 is not the last day of a month|not on the monthly schedule after 2000-01-31; expected 2000-02-29/);
failCase('monthly: a non-month-end date', () => un(unRow('2000-06-30'), (l) => l.replace('2000-06-30', '2000-06-29')), /on 2000-06-29 is not the last day of a month, as monthly data must be/);
failCase('monthly: the first of the month instead of the last', () => un(unRow('1999-04-30'), (l) => l.replace('1999-04-30', '1999-04-01')), /on 1999-04-01 is not the last day of a month/);
failCase('monthly: a non-leap February dated the 29th is not a real date', () => un(unRow('2001-02-28'), (l) => l.replace('2001-02-28', '2001-02-29')), /"2001-02-29" is not a real date/);
failCase('monthly: a month repeated', () => un(unRow('1990-10-31'), (l) => [l, l]), /unemployment_rate \(Australia\) on 1990-10-31: duplicate of line \d+/);
failCase('monthly: the latest month removed (rows fall against the lock)', () => un(unRow('2026-10-31'), () => null), /unemployment-rate\/data\.lock\.json: unemployment_rate \(Australia\) has 584 rows, fewer than the 585/);
failCase('monthly: a rate outside the plausible range', () => un(unRow('1995-03-31'), (l) => setValue(l, '16.0')), /unemployment_rate \(Australia\) on 1995-03-31 is 16, outside the plausible range 0 to 15/);
failCase('monthly: a month-to-month jump over the step limit', () => un(unRow('1995-03-31'), (l) => setValue(l, '14.0')), /moves .* per cent from .*, more than the limit of 35 per cent/);
failCase('monthly: a past month revised by 0.5 is blocked', () => un(unRow('2008-06-30'), (l) => setValue(l, String(Math.round((Number(l.split(',')[4]) + 0.5) * 10) / 10))), /unemployment_rate \(Australia\) on 2008-06-30 \(2008-06\) was [\d.]+ when last accepted and is now [\d.]+, a change of \+0\.5 \(the change is more than 0\.3\)/);
failCase('the pct unit is refused if format.ts cannot format it', () => editFile(p('src', 'lib', 'format.ts'), (t) => t.replaceAll("unit === 'pct')", "unit === 'pctx')")), /src\/lib\/format\.ts: formats the units .* but scripts\/validate\.mjs lists/);
failCase('the pct unit is refused on a series if mistyped', () => un(unRow('2008-06-30'), (l) => { const c = l.split(','); c[5] = 'percent'; return c.join(','); }), /the unit "percent" is not one the site can format \(aud_million, pct_gdp, pct, index, count, rate, days, per_day\)/);
plainCase('monthly: a past month revised by 0.2 only warns', () => {
  un(unRow('2008-06-30'), (l) => setValue(l, String(Math.round((Number(l.split(',')[4]) + 0.2) * 10) / 10)));
  const r = run();
  return check('revised 0.2', r.code === 0 && /WARNING: metrics\/unemployment-rate\/data\.csv: data has changed since it was last accepted \(1 accepted figure revised/.test(r.out), `exit ${r.code}\n${r.out}`);
});
plainCase('monthly: a new month on the end (28 days after a leap-year February too) passes', () => {
  const lines = readText(dataPath(UN)).split('\n').filter((l) => l !== '');
  const last = lines.at(-1).split(',');
  last[0] = '2026-11-30'; last[1] = '2026-11'; last[4] = '4.8';
  writeFileSync(dataPath(UN), lines.concat([last.join(',')]).join('\n') + '\n');
  const r = run();
  return check('new month', r.code === 0 && !/FAIL/.test(r.out), `exit ${r.code}\n${r.out}`);
});
plainCase('monthly: a December to January step crosses the year', () => {
  // 1999-12-31 and 2000-01-31 are both in the real data; removing both must name both
  un((l) => l.startsWith('1999-12-31,') || l.startsWith('2000-01-31,'), () => null);
  const r = run();
  return check('year end', r.code !== 0 && /is missing 1999-12-31, 2000-01-31; the rows jump from 1999-11-30 to 2000-02-29/.test(r.out), r.out);
});

// ---- quarterly data (inflation: two quarterly series and one monthly series in one file)
const INF = 'inflation';
const inf = (match, fn) => editRows(match, fn, INF);
const bump = (by) => (l) => setValue(l, String(Math.round((Number(l.split(',')[4]) + by) * 10) / 10));
failCase('quarterly: delete a middle quarter', () => inf(row('2000-06-30', 'headline_quarterly'), () => null), /headline_quarterly \(Australia\) is missing 2000-06-30; the rows jump from 2000-03-31 to 2000-09-30/);
failCase('quarterly: delete two quarters in a row', () => inf((l) => (l.startsWith('2000-06-30,') || l.startsWith('2000-09-30,')) && l.includes(',trimmed_mean_quarterly,'), () => null), /trimmed_mean_quarterly \(Australia\) is missing 2000-06-30, 2000-09-30; the rows jump from 2000-03-31 to 2000-12-31/);
failCase('quarterly: delete a December quarter (the step crosses the year)', () => inf(row('1999-12-31', 'headline_quarterly'), () => null), /headline_quarterly \(Australia\) is missing 1999-12-31; the rows jump from 1999-09-30 to 2000-03-31/);
failCase('quarterly: a date that is not the last day of its month', () => inf(row('2000-06-30', 'headline_quarterly'), (l) => l.replace('2000-06-30', '2000-06-29')), /on 2000-06-29 is not the last day of March, June, September or December, as quarterly data must be/);
failCase('quarterly: a month end that is not a quarter end', () => inf(row('2000-06-30', 'trimmed_mean_quarterly'), (l) => l.replace('2000-06-30', '2000-07-31')), /on 2000-07-31 is not the last day of March, June, September or December/);
failCase('quarterly: the first day of the quarter instead of the last', () => inf(row('2000-03-31', 'headline_quarterly'), (l) => l.replace('2000-03-31', '2000-01-01')), /on 2000-01-01 is not the last day of March, June, September or December/);
failCase('quarterly: a quarter repeated', () => inf(row('1990-09-30', 'headline_quarterly'), (l) => [l, l]), /headline_quarterly \(Australia\) on 1990-09-30: duplicate of line \d+/);
failCase('quarterly: the latest quarter removed (rows fall against the lock)', () => inf(row('2026-09-30', 'headline_quarterly'), () => null), /inflation\/data\.lock\.json: headline_quarterly \(Australia\) has 306 rows, fewer than the 307/);
failCase('quarterly: headline above its plausible range', () => inf(row('1995-03-31', 'headline_quarterly'), (l) => setValue(l, '35.0')), /headline_quarterly \(Australia\) on 1995-03-31 is 35, outside the plausible range -5 to 30/);
failCase('quarterly: trimmed mean above its plausible range', () => inf(row('1995-03-31', 'trimmed_mean_quarterly'), (l) => setValue(l, '16.0')), /trimmed_mean_quarterly \(Australia\) on 1995-03-31 is 16, outside the plausible range -2 to 15/);
failCase('quarterly: monthly series in the same file still checks its months', () => inf(row('2025-07-31', 'headline_monthly'), () => null), /headline_monthly \(Australia\) is missing 2025-07-31; the rows jump from 2025-06-30 to 2025-08-31/);
failCase('quarterly: a past headline quarter revised by 0.2 is blocked (limit 0.1)', () => inf(row('2008-06-30', 'headline_quarterly'), bump(0.2)), /headline_quarterly \(Australia\) on 2008-06-30 \(2008-Q2\) was [\d.]+ when last accepted and is now [\d.]+, a change of \+0\.2 \(the change is more than 0\.1\)/);
failCase('quarterly: a past trimmed mean quarter revised by 0.4 is blocked (limit 0.3)', () => inf(row('2008-06-30', 'trimmed_mean_quarterly'), bump(0.4)), /trimmed_mean_quarterly \(Australia\) on 2008-06-30 \(2008-Q2\) was [\d.]+ when last accepted and is now [\d.]+, a change of \+0\.4 \(the change is more than 0\.3\)/);
failCase('quarterly: a past monthly headline figure revised by 0.2 is blocked (limit 0.1)', () => inf(row('2025-12-31', 'headline_monthly'), bump(0.2)), /headline_monthly \(Australia\) on 2025-12-31 \(2025-12\) was [\d.]+ when last accepted and is now [\d.]+, a change of \+0\.2 \(the change is more than 0\.1\)/);
failCase('quarterly: a sign flip on a past headline quarter is blocked', () => inf(row('2000-03-31', 'headline_quarterly'), (l) => setValue(l, String(-Number(l.split(',')[4])))), /headline_quarterly \(Australia\) on 2000-03-31 \(2000-Q1\) was [\d.]+ when last accepted and is now -[\d.]+/);
failCase('quarterly: an unknown frequency names quarterly among the known ones', () => editFile(p('metrics', INF, 'metric.yml'), (t) => t.replace('frequency: quarterly', 'frequency: weekly')), /series "headline_quarterly" has frequency "weekly", which the validator does not know\. Known: annual, monthly, quarterly/);
failCase('quarterly: a series with no frequency at all is refused', () => editFile(p('metrics', INF, 'metric.yml'), (t) => t.replace('    frequency: quarterly\n    plausible: {min: -5, max: 30}', '    plausible: {min: -5, max: 30}')), /series "headline_quarterly" has no "frequency"/);
plainCase('quarterly: a past headline quarter revised by exactly 0.1 only warns', () => {
  inf(row('2008-06-30', 'headline_quarterly'), bump(0.1));
  // the wages page holds a copy of this series, which must be revised in step
  editRows(row('2008-06-30', 'price_growth'), bump(0.1), 'wages-and-prices');
  const r = run();
  return check('revised 0.1', r.code === 0 && /WARNING: metrics\/inflation\/data\.csv: data has changed since it was last accepted \(1 accepted figure revised/.test(r.out), `exit ${r.code}\n${r.out}`);
});
plainCase('quarterly: no step check is needed (a series that crosses zero passes without max_step_pct)', () => {
  const t = readText(p('metrics', INF, 'metric.yml'));
  const ok = !/^\s+max_step_pct:/m.test(t);
  const r = run();
  return check('no step check', ok && r.code === 0 && /PASS inflation: /.test(r.out), `has step check: ${!ok}\n${r.out}`);
});
plainCase('quarterly: a new December quarter on the end passes', () => {
  const lines = readText(dataPath(INF)).split('\n').filter((l) => l !== '');
  const last = lines.filter((l) => l.includes(',headline_quarterly,')).at(-1).split(',');
  last[0] = '2026-12-31'; last[1] = '2026-Q4'; last[4] = '3.8';
  writeFileSync(dataPath(INF), lines.concat([last.join(',')]).join('\n') + '\n');
  const r = run();
  return check('new quarter', r.code === 0 && !/FAIL/.test(r.out), `exit ${r.code}\n${r.out}`);
});
plainCase('quarterly: a new March quarter after a December one passes (year crossing)', () => {
  const lines = readText(dataPath(INF)).split('\n').filter((l) => l !== '');
  const last = lines.filter((l) => l.includes(',headline_quarterly,')).at(-1).split(',');
  const dec = [...last]; dec[0] = '2026-12-31'; dec[1] = '2026-Q4'; dec[4] = '3.8';
  const mar = [...last]; mar[0] = '2027-03-31'; mar[1] = '2027-Q1'; mar[4] = '3.6';
  writeFileSync(dataPath(INF), lines.concat([dec.join(','), mar.join(',')]).join('\n') + '\n');
  const r = run();
  return check('year crossing', r.code === 0 && !/FAIL/.test(r.out), `exit ${r.code}\n${r.out}`);
});

// ---- source files
failCase('change one byte of a source file', () => {
  const f = p('metrics', SLUG, 'sources', 'fbo-2025-26-part-1.docx');
  const b = readFileSync(f);
  b[1000] = b[1000] ^ 1;
  writeFileSync(f, b);
}, /fbo-2025-26-part-1\.docx: the checksum does not match the manifest/);
failCase('delete a source file', () => rmSync(p('metrics', SLUG, 'sources', 'fbo-2025-26-appendix-b.docx')), /fbo-2025-26-appendix-b\.docx: listed in the manifest but the file is missing/);
failCase('add an unlisted file to sources', () => writeFileSync(p('metrics', SLUG, 'sources', 'extra.txt'), 'hello'), /sources\/extra\.txt: this file is in the sources folder but is not listed/);
failCase('change one byte of a shared source file', () => {
  const f = p('shared', 'sources', 'abs-cpi-1.10001.10.50.Q.csv');
  const b = readFileSync(f);
  b[200] = b[200] === 0x31 ? 0x32 : 0x31;
  writeFileSync(f, b);
}, /shared\/sources\/abs-cpi-1\.10001\.10\.50\.Q\.csv: the checksum does not match/);
failCase('delete a metric manifest', () => rmSync(p('metrics', SLUG, 'sources', 'manifest.json')), /sources\/manifest\.json: the manifest is missing/);

// ---- shared files
failCase('remove a June from cpi_june.csv', () => editFile(p('shared', 'cpi_june.csv'), (t) => t.split('\n').filter((l) => !l.startsWith('2001-06-30,')).join('\n')), /cpi_june\.csv: the 30 June 2001 row is missing/);
failCase('remove the latest June from cpi_june.csv', () => editFile(p('shared', 'cpi_june.csv'), (t) => t.split('\n').filter((l) => !l.startsWith('2026-06-30,')).join('\n')), /inflation-adjusted dollars, but shared\/cpi_june\.csv has no price index for 2026-06-30/);
failCase('make a price index jump by more than 30 per cent', () => editFile(p('shared', 'cpi_june.csv'), (t) => t.replace(/^1990-06-30,[0-9.]+,/m, '1990-06-30,999,')), /the index moves .* per cent between 1989-06-30/);
failCase('put events out of order', () => editFile(p('shared', 'events.csv'), (t) => t.replace('1982-10-01,Early 1980s recession\n1991-01-01,Early 1990s recession', '1991-01-01,Early 1990s recession\n1982-10-01,Early 1980s recession')), /events\.csv: line 3: 1982-10-01 is not after 1991-01-01/);
failCase('put a governments date that is not real', () => editFile(p('shared', 'governments.csv'), (t) => t.replace('1972-12-05', '1972-13-05')), /governments\.csv: line 3: "1972-13-05" is not a real date/);

// ---- metric.yml
failCase('remove a required metric.yml field', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace(/^retrieved: .*\n/m, '')), /metric\.yml: required field "retrieved" is missing/);
failCase('use an unknown frequency', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('frequency: annual', 'frequency: weekly')), /series "gross_debt" has frequency "weekly", which the validator does not know/);
failCase('leave out a series frequency', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('    frequency: annual\n', '')), /series "gross_debt" has no "frequency"/);
failCase('leave out a plausible range', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('    plausible: {min: 0, max: 3000000}\n', '')), /series "gross_debt" needs "plausible"/);
failCase('name an undeclared series in a view', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('      - series: gross_debt_pct_gdp\n        label: Gross debt\n', '      - series: ghost_series\n        label: Gross debt\n')), /view "share_of_gdp" uses series "ghost_series", which has no rows in data\.csv/);
failCase('enforce max_step_pct', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('    plausible: {min: 0, max: 3000000}\n', '    plausible: {min: 0, max: 3000000}\n    max_step_pct: 5\n')), /gross_debt \(Commonwealth\) on \d{4}-06-30 moves [\d.]+ per cent from .* more than the limit of 5 per cent/);

// ---- the lock file
failCase('delete the lock file', () => rmSync(p('metrics', SLUG, 'data.lock.json')), /data\.lock\.json: there is no lock file\. Run "npm run accept-data"/);

// ---- cases that must not fail, or must behave in a particular way
plainCase('max_step_floor stops max_step_pct applying below the floor', () => {
  editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('    plausible: {min: 0, max: 3000000}\n', '    plausible: {min: 0, max: 3000000}\n    max_step_pct: 5\n    max_step_floor: 100000000\n'));
  const r = run();
  return check('max_step_floor', r.code === 0, `expected a pass, got exit ${r.code}\n${r.out}`);
});

plainCase('one historical value changed within range gives a warning and exit 0', () => {
  editRows(row('1990-06-30', 'gross_debt'), (l) => setValue(l, String(Number(l.split(',')[4]) + 1)));
  const r = run();
  return (
    check('warning case', r.code === 0, `expected exit 0, got ${r.code}\n${r.out}`) &&
    check('warning case', /WARNING: metrics\/commonwealth-debt\/data\.csv: data has changed since it was last accepted/.test(r.out), `no WARNING line\n${r.out}`)
  );
});

plainCase('--accept refuses on a corrupted copy and leaves the lock file alone', () => {
  editRows(row('1990-06-30', 'gross_debt'), (l) => setValue(l, 'abc'));
  const before = sha(p('metrics', SLUG, 'data.lock.json'));
  const r = run('--accept');
  return (
    check('accept refuses', r.code !== 0, `expected a non-zero exit, got ${r.code}\n${r.out}`) &&
    check('accept refuses', /Nothing was accepted/.test(r.out), `no refusal message\n${r.out}`) &&
    check('accept refuses', sha(p('metrics', SLUG, 'data.lock.json')) === before, 'the lock file changed')
  );
});

plainCase('--accept writes the lock file on a clean copy, and the copy then passes', () => {
  rmSync(p('metrics', SLUG, 'data.lock.json'));
  const a = run('--accept');
  const v = run();
  return (
    check('accept clean', a.code === 0 && existsSync(p('metrics', SLUG, 'data.lock.json')), `accept exit ${a.code}\n${a.out}`) &&
    check('accept clean', v.code === 0, `validate after accept exit ${v.code}\n${v.out}`)
  );
});

plainCase('--accept does not hide a fall in rows (the lock is not lowered)', () => {
  editRows((l) => l.startsWith('2026-06-30,'), () => null);
  const before = sha(p('metrics', SLUG, 'data.lock.json'));
  const r = run('--accept');
  return (
    check('accept fall', r.code !== 0, `expected a non-zero exit, got ${r.code}`) &&
    check('accept fall', sha(p('metrics', SLUG, 'data.lock.json')) === before, 'the lock file changed')
  );
});

// ---- protection of past figures (revisions to accepted values)
const HINT = /accept-data -- --accept-revisions/;
const lockFile = () => p('metrics', SLUG, 'data.lock.json');
const setTo = (v) => (l) => setValue(l, String(v));
const revisedBlock = (name, date, series, newValue, mustFail, mustName) =>
  mustFail
    ? failCase(name, () => editRows(row(date, series), setTo(newValue)), mustName)
    : plainCase(name, () => {
        editRows(row(date, series), setTo(newValue));
        const r = run();
        return (
          check(name, r.code === 0, `expected exit 0, got ${r.code}\n${r.out}`) &&
          check(name, /WARNING: .*data has changed since it was last accepted/.test(r.out), `no WARNING line\n${r.out}`)
        );
      });

failCase('revision: 2007-08 net debt flips sign (-39958 to 39958)', () => editRows(row('2008-06-30', 'net_debt'), setTo(39958)),
  /net_debt \(Commonwealth\) on 2008-06-30 \(2007-08\) was -39958 when last accepted and is now 39958.*accept-data -- --accept-revisions/);
revisedBlock('revision: 2024-25 gross debt share moves 0.2 points (passes with a warning)', '2025-06-30', 'gross_debt_pct_gdp', '33.6', false);
revisedBlock('revision: 2024-25 gross debt share moves 1.0 point (fails)', '2025-06-30', 'gross_debt_pct_gdp', '34.4', true, /gross_debt_pct_gdp \(Commonwealth\) on 2025-06-30 \(2024-25\) was 33\.4 .* is now 34\.4, a change of \+1/);
revisedBlock('revision: 2024-25 gross debt up $1m (at max_abs, passes with a warning)', '2025-06-30', 'gross_debt', 928640, false);
revisedBlock('revision: 1990-91 gross debt digits transposed, 48723 to 48732 (fails)', '1991-06-30', 'gross_debt', 48732, true, /gross_debt \(Commonwealth\) on 1991-06-30 \(1990-91\) was 48723 .* is now 48732, a change of \+9/);
revisedBlock('revision: 2025-26 net debt digits transposed, 549969 to 549696 (fails)', '2026-06-30', 'net_debt', 549696, true, /net_debt \(Commonwealth\) on 2026-06-30 .* a change of -273/);
revisedBlock('revision: 2024-25 gross debt up $10,000m (fails)', '2025-06-30', 'gross_debt', 938639, true, /gross_debt \(Commonwealth\) on 2025-06-30 .* a change of \+10000/);
revisedBlock('revision: 2005-06 net debt 331 to -331 (fails)', '2006-06-30', 'net_debt', -331, true, /net_debt \(Commonwealth\) on 2006-06-30 \(2005-06\) was 331 .* is now -331/);

// The max_pct and pct_floor rule, tested with its own tolerance written into the temporary copy.
const withPctRule = () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replaceAll('revision: {max_abs: 1}', 'revision: {max_abs: 500, max_pct: 1, pct_floor: 5000}'));
plainCase('max_pct rule: gross debt up $400m passes with a warning', () => {
  withPctRule();
  editRows(row('2025-06-30', 'gross_debt'), setTo(929039));
  const r = run();
  return check('max_pct pass', r.code === 0 && /WARNING: .*data has changed/.test(r.out), `exit ${r.code}\n${r.out}`);
});
plainCase('max_pct rule: gross debt up $10,000m (over 500 and 1 per cent) fails', () => {
  withPctRule();
  editRows(row('2025-06-30', 'gross_debt'), setTo(938639));
  const r = run();
  return check('max_pct fail', r.code !== 0 && /a change of \+10000/.test(r.out), `exit ${r.code}\n${r.out}`);
});
plainCase('max_pct rule: net debt 331 to 200 (under pct_floor, under max_abs) passes with a warning', () => {
  withPctRule();
  editRows(row('2006-06-30', 'net_debt'), setTo(200));
  const r = run();
  return check('pct_floor pass', r.code === 0, `exit ${r.code}\n${r.out}`);
});

plainCase('revision failure line names the file, series, jurisdiction, date, period, old, new, change and the way to accept', () => {
  editRows(row('2008-06-30', 'net_debt'), setTo(39958));
  const line = run().out.split('\n').find((l) => l.startsWith('FAIL:')) ?? '';
  return check('revision line', /^FAIL: metrics\/commonwealth-debt\/data\.csv: net_debt \(Commonwealth\) on 2008-06-30 \(2007-08\) was -39958 .* is now 39958, a change of \+79916 \(the sign has changed\)\. If this revision is genuine, check it against the source and accept it with: npm run accept-data -- --accept-revisions$/.test(line), line);
});

plainCase('plain accept-data refuses on a large revision and leaves the lock file unchanged', () => {
  editRows(row('2008-06-30', 'net_debt'), setTo(39958));
  const before = readFileSync(lockFile());
  const r = run('--accept');
  return (
    check('accept refuses revision', r.code !== 0 && HINT.test(r.out) && /Nothing was accepted/.test(r.out), `exit ${r.code}\n${r.out}`) &&
    check('accept refuses revision', Buffer.compare(before, readFileSync(lockFile())) === 0, 'the lock file changed')
  );
});

plainCase('accept-data --accept-revisions writes the lock, prints the revision, and validate then passes with no warning', () => {
  editRows(row('2008-06-30', 'net_debt'), setTo(39958));
  const before = readFileSync(lockFile());
  const a = run('--accept', '--accept-revisions');
  const v = run();
  const lock = JSON.parse(readText(lockFile()));
  const nd = lock.series.find((s) => s.series === 'net_debt');
  return (
    check('accept revisions', a.code === 0 && /ACCEPTED REVISION: .*net_debt \(Commonwealth\) on 2008-06-30/.test(a.out), `exit ${a.code}\n${a.out}`) &&
    check('accept revisions', Buffer.compare(before, readFileSync(lockFile())) !== 0 && nd.values['2008-06-30'] === '39958', 'the lock was not updated') &&
    check('accept revisions', v.code === 0 && !/WARNING/.test(v.out) && /Validation passed/.test(v.out), `validate after: exit ${v.code}\n${v.out}`)
  );
});

plainCase('--accept-revisions does not override a different failure (a value outside the plausible range)', () => {
  editRows(row('2008-06-30', 'net_debt'), setTo(39958));
  editRows(row('2000-06-30', 'gross_debt_pct_gdp'), setTo(150));
  const before = readFileSync(lockFile());
  const r = run('--accept', '--accept-revisions');
  return (
    check('accept revisions refuses', r.code !== 0 && /outside the plausible range 0 to 100/.test(r.out) && /Nothing was accepted/.test(r.out), `exit ${r.code}\n${r.out}`) &&
    check('accept revisions refuses', !/ACCEPTED REVISION/.test(r.out), 'it printed an accepted revision although it refused') &&
    check('accept revisions refuses', Buffer.compare(before, readFileSync(lockFile())) === 0, 'the lock file changed')
  );
});

plainCase('--accept-revisions does not hide a fall in rows', () => {
  editRows((l) => l.startsWith('2026-06-30,'), () => null);
  const before = readFileSync(lockFile());
  const r = run('--accept-revisions');
  return (
    check('revisions rows fall', r.code !== 0 && /Rows must never fall/.test(r.out), `exit ${r.code}\n${r.out}`) &&
    check('revisions rows fall', Buffer.compare(before, readFileSync(lockFile())) === 0, 'the lock file changed')
  );
});

failCase('a series without a revision tolerance fails', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace(/^    revision: \{max_abs: 1\}\n/m, '')), /series "(gross_debt|net_debt)" has no "revision" tolerance/);
failCase('a revision tolerance with an unknown field fails', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('revision: {max_abs: 0.5}', 'revision: {max_abs: 0.5, max_percent: 3}')), /has a "revision" field "max_percent"/);
failCase('a revision tolerance without max_abs fails', () => editFile(p('metrics', SLUG, 'metric.yml'), (t) => t.replace('revision: {max_abs: 0.5}', 'revision: {max_pct: 3}')), /needs "revision" to have "max_abs"/);

plainCase('an old-format lock fails with the upgrade message; plain accept-data upgrades it; validate then passes', () => {
  const lock = JSON.parse(readText(lockFile()));
  delete lock.lock_version;
  for (const s of lock.series) delete s.values;
  writeFileSync(lockFile(), JSON.stringify(lock, null, 2) + '\n');
  const v1 = run();
  const a = run('--accept');
  const v2 = run();
  const upgraded = JSON.parse(readText(lockFile()));
  return (
    check('old lock', v1.code !== 0 && /lock file is in the old format.*Run "npm run accept-data" once to upgrade it/.test(v1.out), `validate: exit ${v1.code}\n${v1.out}`) &&
    check('old lock', a.code === 0 && upgraded.lock_version === 2 && Object.keys(upgraded.series[0].values).length === 56, `accept: exit ${a.code}\n${a.out}`) &&
    check('old lock', v2.code === 0 && !/WARNING/.test(v2.out), `validate after: exit ${v2.code}\n${v2.out}`)
  );
});

plainCase('accept-data does not upgrade an old-format lock when another check fails', () => {
  const lock = JSON.parse(readText(lockFile()));
  delete lock.lock_version;
  for (const s of lock.series) delete s.values;
  writeFileSync(lockFile(), JSON.stringify(lock, null, 2) + '\n');
  editRows(row('1990-06-30', 'gross_debt'), (l) => setValue(l, 'abc'));
  const before = readFileSync(lockFile());
  const r = run('--accept');
  return check('old lock refuses', r.code !== 0 && Buffer.compare(before, readFileSync(lockFile())) === 0, `exit ${r.code}\n${r.out}`);
});

plainCase('appending a new year is not treated as a revision', () => {
  const lines = readText(dataPath()).split('\n');
  const add = [];
  for (const l of lines) {
    if (l.startsWith('2026-06-30,')) {
      const c = l.split(',');
      c[0] = '2027-06-30';
      c[1] = '2026-27';
      c[4] = c[2].endsWith('_pct_gdp') ? '34' : String(Number(c[4]) + 100000);
      add.push(c.join(','));
    }
  }
  // a new year also needs a price index for the inflation-adjusted views
  editFile(p('shared', 'cpi_june.csv'), (t) => t.trimEnd() + '\n2027-06-30,105.00,base period 25 as coded by the ABS\n');
  writeFileSync(dataPath(), lines.filter((l) => l !== '').concat(add).join('\n') + '\n');
  const r = run();
  return check('new year', r.code === 0 && !/was .* when last accepted/.test(r.out), `exit ${r.code}\n${r.out}`);
});

plainCase('every problem is printed, not just the first', () => {
  editRows(row('1990-06-30', 'gross_debt'), (l) => setValue(l, 'abc'));
  editRows(row('2000-06-30', 'gross_debt_pct_gdp'), (l) => setValue(l, '150'));
  const r = run();
  return check('all problems', /the value "abc"/.test(r.out) && /outside the plausible range 0 to 100/.test(r.out), r.out);
});

// ---- a series that is a copy of another metric's series (copy_of in metric.yml)
const WP = 'wages-and-prices';
const INFL = 'inflation';
const ymlPath = (slug) => p('metrics', slug, 'metric.yml');
failCase('copy_of: a copied row differs from the other page', () => editRows(row('2026-09-30', 'price_growth'), (l) => setValue(l, '4.0'), WP),
  /wages-and-prices\/data\.csv: line \d+, price_growth \(Australia\) on 2026-09-30 is 4\.0 \(pct\), but the inflation page's headline_quarterly for that date is 3\.9\. price_growth must equal headline_quarterly on the inflation page/);
failCase('copy_of: the other page changes and the copy does not', () => editRows(row('2010-06-30', 'headline_quarterly'), (l) => setValue(l, '9.9'), INFL),
  /price_growth \(Australia\) on 2010-06-30 is .*but the inflation page's headline_quarterly for that date is 9\.9/);
failCase('copy_of: a copied row has no row on the other page', () => editRows(row('2005-03-31', 'headline_quarterly'), () => null, INFL),
  /price_growth \(Australia\) on 2005-03-31 .*but metrics\/inflation\/data\.csv has no headline_quarterly row for 2005-03-31/);
failCase('copy_of: the other metric names a series that does not exist', () => editFile(ymlPath(WP), (t) => t.replace('series: headline_quarterly}', 'series: headline_nothing}')),
  /series "price_growth" is a copy of headline_nothing in inflation, but metrics\/inflation\/data\.csv has no rows for that series/);
failCase('copy_of: the other metric has no data.csv', () => rmSync(p('metrics', INFL, 'data.csv')), /series "price_growth" is a copy of inflation \(headline_quarterly\), but metrics\/inflation\/data\.csv is missing/);
failCase('copy_of: written the wrong way', () => editFile(ymlPath(WP), (t) => t.replace('copy_of: {metric: inflation, series: headline_quarterly}', 'copy_of: inflation')),
  /series "price_growth" has a "copy_of" that is not \{metric: <another metric's folder name>, series: <its series id>\}/);
failCase('copy_of: a copy of itself', () => editFile(ymlPath(WP), (t) => t.replace('copy_of: {metric: inflation,', 'copy_of: {metric: wages-and-prices,')), /has a "copy_of" that is not/);
failCase('changing one past wage figure by 0.5 blocks (revision tolerance 0.3)', () => editRows(row('2012-06-30', 'wage_growth'), (l) => setValue(l, String(Number(l.split(',')[4]) + 0.5)), WP),
  /wage_growth \(Australia\) on 2012-06-30 \(2012-Q2\) was .* when last accepted and is now .*, a change of \+0\.5 \(the change is more than 0\.3\)/);
failCase('a manifest reference with a bad path is refused', () => editFile(p('metrics', WP, 'sources', 'manifest.json'), (t) => t.replace('"path": "metrics/inflation/data.csv"', '"path": "../../etc/passwd"')),
  /the entry for "copied-from-metrics-inflation-data\.csv" has a "path" that is not a file inside a metrics folder/);
failCase('a manifest reference with a bad checksum is refused', () => editFile(p('metrics', WP, 'sources', 'manifest.json'), (t) => {
  const m = JSON.parse(t);
  m['copied-from-metrics-inflation-data.csv'].sha256 = 'abc';
  return JSON.stringify(m, null, 2) + '\n';
}), /the entry for "copied-from-metrics-inflation-data\.csv" has no valid sha256 and bytes/);
plainCase('a manifest reference is not looked for in the sources folder, and the other file may change after the copy', () => {
  // the inflation page gets a new quarter and its file changes; the copy's recorded checksum is then out of date, which is not an error
  const lines = readText(dataPath(INFL)).split('\n').filter((l) => l !== '');
  const last = lines.filter((l) => l.includes(',headline_quarterly,')).at(-1).split(',');
  last[0] = '2026-12-31'; last[1] = '2026-Q4'; last[4] = '4.0';
  writeFileSync(dataPath(INFL), lines.concat([last.join(',')]).join('\n') + '\n');
  const r = run();
  return check('reference', r.code === 0 && /PASS wages-and-prices/.test(r.out), `exit ${r.code}\n${r.out}`);
});

// ---- rents: the index unit, a derived series (year_ended_change), jurisdictions and the state panel
const RENTS = 'rents';
const rentsRow = (date, series, jur) => (l) => l.startsWith(`${date},`) && l.includes(`,${series},${jur},`);
const rents = (match, fn) => editRows(match, fn, RENTS);
const rentsYml = () => ymlPath(RENTS);
const swap = (t, a, b) => t.replace(a, '@@').replace(b, a).replace('@@', b);

// the index unit
plainCase('the index unit is known to the checker and the site', () => {
  const r = run();
  return check('index unit', r.code === 0 && /PASS rents: 568 rows, 2 series, 1972-09-30 to 2026-09-30/.test(r.out) && /format\.ts/.test(readText(join(REPO, 'src', 'lib', 'format.ts'))) && /unit === 'index'/.test(readText(p('src', 'lib', 'format.ts'))), `exit ${r.code}\n${r.out}`);
});
failCase('the index unit is not formatted by the site (format.ts lacks it)', () => editFile(p('src', 'lib', 'format.ts'), (t) => t.replaceAll("  if (unit === 'index') return indexText(v);\n", '').replace("  if (unit === 'index') return String(+v.toFixed(2));\n", '')),
  /src\/lib\/format\.ts: formats the units \[aud_million, count, days, pct, pct_gdp, per_day, rate\] but scripts\/validate\.mjs lists \[aud_million, count, days, index, pct, pct_gdp, per_day, rate\]/);
failCase('an index figure outside its plausible range', () => rents(rentsRow('2020-12-31', 'rents_index_quarterly', 'Australia'), (l) => setValue(l, '650.00')), /rents_index_quarterly \(Australia\) on 2020-12-31 is 650, outside the plausible range 1 to 500/);
failCase('an index figure given another unit (a series has one unit)', () => rents(rentsRow('2020-12-31', 'rents_index_quarterly', 'Australia'), (l) => { const c = l.split(','); c[5] = 'pct'; return c.join(','); }), /series "rents_index_quarterly" has more than one unit \(index, pct\)/);
failCase('quarterly: delete a middle quarter of the index', () => rents(rentsRow('1990-03-31', 'rents_index_quarterly', 'Australia'), () => null), /rents_index_quarterly \(Australia\) is missing 1990-03-31; the rows jump from 1989-12-31 to 1990-06-30/);
failCase('quarterly: an index date that is not the end of a quarter', () => rents(rentsRow('1990-03-31', 'rents_index_quarterly', 'Australia'), (l) => l.replace('1990-03-31', '1990-03-30')), /on 1990-03-30 is not the last day of March, June, September or December/);

// changing one past index quarter by 0.1 blocks (the CPI is not revised)
failCase('changing one past index quarter by 0.1 blocks', () => rents(rentsRow('2024-06-30', 'rents_index_quarterly', 'Australia'), (l) => setValue(l, (Number(l.split(',')[4]) + 0.1).toFixed(2))),
  /rents_index_quarterly \(Australia\) on 2024-06-30 \(2024-Q2\) was [\d.]+ when last accepted and is now [\d.]+, a change of \+0\.1 \(the change is more than 0\.01\)/);
plainCase('a past index quarter changed by 0.01 or less is only a warning', () => {
  rents(rentsRow('2024-06-30', 'rents_index_quarterly', 'Australia'), (l) => setValue(l, (Number(l.split(',')[4]) + 0.01).toFixed(2)));
  const r = run();
  return check('index 0.01', r.code === 0 && /WARNING: metrics\/rents\/data\.csv: data has changed since it was last accepted \(1 accepted figure revised/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('a past monthly figure revised by 0.5 blocks (tolerance 0.1)', () => rents(rentsRow('2025-03-31', 'rents_monthly', 'Australia'), (l) => setValue(l, (Number(l.split(',')[4]) + 0.5).toFixed(1))),
  /rents_monthly \(Australia\) on 2025-03-31 \(2025-03\) was [\d.-]+ when last accepted and is now [\d.-]+, a change of \+0\.5 \(the change is more than 0\.1\)/);

// the derived series
failCase('derived: the index changing so the worked-out change leaves its plausible range', () => rents(rentsRow('2026-09-30', 'rents_index_quarterly', 'Australia'), (l) => setValue(l, '400.00')),
  /rents_quarterly \(Australia\) on 2026-09-30, worked out from rents_index_quarterly 400\.00 on 2026-09-30 and 99\.74 on 2025-09-30, is 301, outside the plausible range -20 to 40/);
failCase('derived: a derived series must not be stored in data.csv', () => editFile(dataPath(RENTS), (t) => t + '2026-09-30,2026-Q3,rents_quarterly,Australia,3.6,pct,actual\n'),
  /series "rents_quarterly" is derived in metric\.yml, so it must not have rows in data\.csv/);
failCase('derived: the series it is worked out from is not declared', () => editFile(rentsYml(), (t) => t.replace('from: rents_index_quarterly, lag: 4', 'from: rents_nothing, lag: 4')),
  /series "rents_quarterly" is worked out from "rents_nothing", which is not in the "series" list/);
failCase('derived: an unknown derive type', () => editFile(rentsYml(), (t) => t.replace('type: year_ended_change', 'type: moving_average')),
  /series "rents_quarterly" has derive type "moving_average", which the site does not know\. Known: year_ended_change/);
failCase('derived: a lag of zero', () => editFile(rentsYml(), (t) => t.replace('lag: 4', 'lag: 0')), /series "rents_quarterly" has a "derive" "lag" that is not a whole number of periods above zero/);
failCase('derived: a derive with no from', () => editFile(rentsYml(), (t) => t.replace('from: rents_index_quarterly, ', '')), /series "rents_quarterly" has a "derive" with no "from"/);
failCase('derived: a field the checker does not know', () => editFile(rentsYml(), (t) => t.replace('lag: 4}', 'lag: 4, round: 2}')), /series "rents_quarterly" has a "derive" field "round" that the checker does not know/);
failCase('derived: worked out from a monthly series but declared quarterly', () => editFile(rentsYml(), (t) => t.replace('from: rents_index_quarterly, lag: 4', 'from: rents_monthly, lag: 4')),
  /series "rents_quarterly" says it is quarterly but the series it is worked out from is monthly/);
plainCase('derived: worked out from another derived series is allowed', () => {
  editFile(rentsYml(), (t) => t.replace('  - id: rents_monthly\n', "  - id: rents_chained\n    label: Chained\n    derive: {type: year_ended_change, from: rents_quarterly, lag: 4}\n    frequency: quarterly\n    plausible: {min: -100000, max: 100000}\n  - id: rents_monthly\n"));
  const r = run();
  return check('chained derive', r.code === 0 && /PASS rents/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('derived: two series worked out from each other', () => editFile(rentsYml(), (t) => t.replace('  - id: rents_monthly\n', "  - id: loop_a\n    label: A\n    derive: {type: sum, from: [loop_b, rents_index_quarterly]}\n    frequency: quarterly\n    plausible: {min: 0, max: 1000}\n  - id: loop_b\n    label: B\n    derive: {type: sum, from: [loop_a, rents_index_quarterly]}\n    frequency: quarterly\n    plausible: {min: 0, max: 1000}\n  - id: rents_monthly\n")),
  /is worked out from itself \(through other derived series\)/);
failCase('derived: no plausible range', () => editFile(rentsYml(), (t) => t.replace('    plausible: {min: -20, max: 40}\n  - id: rents_monthly', '  - id: rents_monthly')), /series "rents_quarterly" needs "plausible"/);
failCase('derived: used in a view but the series entry is removed', () => editFile(rentsYml(), (t) => t.replace(/  - id: rents_quarterly\n[\s\S]*?  - id: rents_monthly\n/, '  - id: rents_monthly\n')),
  /uses series "rents_quarterly", which is not in the "series" list/);
failCase('derived: a gap in the index is reported on the index, and the figures that need the gap are left blank, not reported as wrong', () => rents(rentsRow('1990-03-31', 'rents_index_quarterly', 'Australia'), () => null),
  /rents_index_quarterly \(Australia\) is missing 1990-03-31/);
plainCase('derived: a gap in the index adds no complaint about the derived series', () => {
  rents(rentsRow('1990-03-31', 'rents_index_quarterly', 'Australia'), () => null);
  const r = run();
  return check('gap blank', r.code !== 0 && !/rents_quarterly/.test(r.out.replace(/metrics\/rents\/metric\.yml/g, '')) && /rents_index_quarterly \(Australia\) is missing/.test(r.out), r.out);
});

// the derive code itself: rounding half up, exact sums, gaps
plainCase('derive: (this / four earlier - 1) x 100 is rounded half up to one decimal', () => {
  const got = [
    yearEndedChangeText('103.30', '99.74'), yearEndedChangeText('100.25', '100.00'), yearEndedChangeText('100.05', '100'), yearEndedChangeText('100.04', '100'),
    yearEndedChangeText('105', '100'), yearEndedChangeText('7.55', '7.07'), yearEndedChangeText('8.83', '7.80'),
  ];
  return check('half up', JSON.stringify(got) === JSON.stringify(['3.6', '0.3', '0.1', '0.0', '5.0', '6.8', '13.2']), JSON.stringify(got));
});
plainCase('derive: a tie below zero goes away from zero, and a tiny fall is never "-0.0"', () => {
  const got = [yearEndedChangeText('99.75', '100'), yearEndedChangeText('99.95', '100'), yearEndedChangeText('99.96', '100'), yearEndedChangeText('90', '100')];
  return check('negative', JSON.stringify(got) === JSON.stringify(['-0.3', '-0.1', '0.0', '-10.0']), JSON.stringify(got));
});
plainCase('derive: a figure that is not a number, or an earlier figure that is not above zero, gives no figure', () => {
  const got = [yearEndedChangeText('abc', '100'), yearEndedChangeText('100', '0'), yearEndedChangeText('100', '-5'), yearEndedChangeText('', '100')];
  return check('blank', got.every((x) => x === null), JSON.stringify(got));
});
plainCase('derive: a gap makes the derived figure blank, not wrong', () => {
  const q = ['2020-03-31', '2020-06-30', '2020-09-30', '2020-12-31', '2021-03-31', '2021-06-30', '2021-09-30', '2021-12-31', '2022-03-31'];
  const rows = q.map((d, i) => ({ date: d, period: d, valueText: String(100 + i) }));
  const full = deriveYearEndedChange(rows, 4, 'quarterly').map((r) => r.date);
  const gap = deriveYearEndedChange(rows.filter((r) => r.date !== '2021-03-31'), 4, 'quarterly');
  const have = gap.map((r) => r.date);
  const wrong = gap.find((r) => r.date === '2021-06-30' && r.valueText !== '4.0');
  return check('gap', JSON.stringify(full) === JSON.stringify(q.slice(4)) && JSON.stringify(have) === JSON.stringify(['2021-06-30', '2021-09-30', '2021-12-31', '2022-03-31'].filter((d) => d !== '2021-03-31' && d !== '2022-03-31')) && !wrong,
    `full ${full}\ngap ${have}`) && check('gap', !have.includes('2022-03-31') && !have.includes('2021-03-31'), `gap ${have}`);
});
plainCase('derive: the earlier period is found by date, for quarters, months and leap years', () => {
  return check('shift', shiftPeriods('2026-09-30', 4, 'quarterly') === '2025-09-30' && shiftPeriods('2024-02-29', 12, 'monthly') === '2023-02-28'
    && shiftPeriods('2026-03-31', 1, 'quarterly') === '2025-12-31' && shiftPeriods('2026-09-30', 4, 'annual') === null, 'shift');
});

// jurisdictions: a series with several must be picked with "jurisdiction:"
failCase('jurisdiction: a view line uses a series with nine jurisdictions without naming one', () => editFile(rentsYml(), (t) => t.replace('      - series: rents_monthly\n        jurisdiction: Australia\n        label: Rents, monthly CPI', '      - series: rents_monthly\n        label: Rents, monthly CPI')),
  /view "growth" uses series "rents_monthly", which has figures for 9 jurisdictions \(Australia, Australian Capital Territory, New South Wales.*\)\. Name one with "jurisdiction:"/);
failCase('jurisdiction: a tile asks for a jurisdiction the series does not have', () => editFile(rentsYml(), (t) => t.replace('    series: rents_monthly\n    jurisdiction: Australia\n    sub_month: true', '    series: rents_monthly\n    jurisdiction: Atlantis\n    sub_month: true')),
  /tile "Rents, monthly CPI" asks for series "rents_monthly" in the jurisdiction "Atlantis", which has no figures/);
failCase('jurisdiction: a table column uses the series without naming one', () => editFile(rentsYml(), (t) => t.replace('      series: rents_monthly\n      jurisdiction: Australia\n', '      series: rents_monthly\n')), /the table uses series "rents_monthly", which has figures for 9 jurisdictions/);
failCase('city: delete a middle month of one city', () => rents(rentsRow('2025-03-31', 'rents_monthly', 'Tasmania'), () => null), /rents_monthly \(Tasmania\) is missing 2025-03-31; the rows jump from 2025-02-28 to 2025-04-30/);
failCase('city: a city figure outside the plausible range', () => rents(rentsRow('2025-03-31', 'rents_monthly', 'Queensland'), (l) => setValue(l, '55.0')), /rents_monthly \(Queensland\) on 2025-03-31 is 55, outside the plausible range -20 to 40/);
failCase('city: the latest month of one city removed (rows fall against the lock)', () => rents(rentsRow('2026-09-30', 'rents_monthly', 'Victoria'), () => null), /rents\/data\.lock\.json: rents_monthly \(Victoria\) has 38 rows, fewer than the 39/);
failCase('city: a past city figure revised by 0.5 blocks', () => rents(rentsRow('2025-03-31', 'rents_monthly', 'Western Australia'), (l) => setValue(l, (Number(l.split(',')[4]) + 0.5).toFixed(1))), /rents_monthly \(Western Australia\) on 2025-03-31 .* a change of \+0\.5 \(the change is more than 0\.1\)/);

// the state and territory panel
failCase('panel: state_panel is true but there is no config', () => editFile(rentsYml(), (t) => t.replace(/state_panel_config:[\s\S]*?\n\n# Sources/, '\n# Sources')), /"state_panel" is true but there is no "state_panel_config"/);
failCase('panel: two places swapped (the order is fixed)', () => editFile(rentsYml(), (t) => swap(t, '{jurisdiction: Victoria, abbreviation: Vic, name: Melbourne}', '{jurisdiction: Queensland, abbreviation: Qld, name: Brisbane}')),
  /state panel place 2 is "Queensland" but must be "Victoria": the order is fixed \(NSW, Vic, Qld, WA, SA, Tas, ACT, NT\)/);
failCase('panel: a place left out', () => editFile(rentsYml(), (t) => t.replace('    - {jurisdiction: Northern Territory, abbreviation: NT, name: Darwin}\n', '')), /the state panel must list exactly 8 places in the fixed order \(NSW, Vic, Qld, WA, SA, Tas, ACT, NT\); it lists 7/);
failCase('panel: a wrong abbreviation', () => editFile(rentsYml(), (t) => t.replace('abbreviation: Tas,', 'abbreviation: TAS,')), /state panel place 6 \(Tasmania\) has the abbreviation "TAS" but must have "Tas"/);
failCase('panel: a place with no name', () => editFile(rentsYml(), (t) => t.replace(', name: Hobart}', ', name: ""}')), /state panel place 6 \(Tasmania\) has no "name"/);
failCase('panel: the note is missing', () => editFile(rentsYml(), (t) => t.replace(/  note: "Each chart[^\n]*\n/, '')), /"state_panel_config" needs "note", as text/);
failCase('panel: the heading is empty', () => editFile(rentsYml(), (t) => t.replace('heading: Capital cities', 'heading: ""')), /"state_panel_config" needs "heading", as text/);
failCase('panel: the table headings are not three', () => editFile(rentsYml(), (t) => t.replace('headers: [Capital city, Month, Rents over twelve months]', 'headers: [Capital city, Month]')), /"state_panel_config" needs "headers", a list of three column headings/);
failCase('panel: the national line has no rows', () => editFile(rentsYml(), (t) => t.replace('national: Australia', 'national: Atlantis')), /the state panel needs rents_monthly for "Atlantis", but data\.csv has no rows for it/);
failCase('panel: the panel series is not in the series list', () => editFile(rentsYml(), (t) => t.replace('  series: rents_monthly\n  national', '  series: rents_nonesuch\n  national')), /the state panel series "rents_nonesuch" must be in the "series" list/);
failCase('panel: the cities end in different months', () => editFile(dataPath(RENTS), (t) => t.split('\n').filter((l) => !(l.startsWith('2026-09-30,') && l.includes(',rents_monthly,Tasmania,'))).join('\n')), /the places in the state panel do not all end on the same date \(2026-08-31, 2026-09-30\)/);
failCase('panel: state_panel is not true or false', () => editFile(rentsYml(), (t) => t.replace('state_panel: true', 'state_panel: yes please')), /"state_panel" must be true or false/);

// ---- social housing: value codes, sum and ratio derived series, a derived panel series, the edition map
const SH = 'social-housing';
const shRow = (date, series, jur) => (l) => l.startsWith(`${date},`) && l.includes(`,${series},${jur},`);
const sh = (match, fn) => editRows(match, fn, SH);
const shYml = () => ymlPath(SH);
const shRun = () => run();
plainCase('social housing: the clean copy passes with codes in the data and worked-out series', () => {
  const r = shRun();
  const t = readText(dataPath(SH));
  return check('sh clean', r.code === 0 && /PASS social-housing: 450 rows, 5 series, 2016-06-30 to 2025-06-30/.test(r.out) && /,somih,Victoria,\.\.,count,actual/.test(t) && /2016-06-30,2016,somih,Northern Territory,na,count,actual/.test(t), `exit ${r.code}\n${r.out}`);
});
failCase('codes: a value that is neither a number nor a code', () => sh(shRow('2025-06-30', 'public_housing', 'Victoria'), (l) => setValue(l, 'n/a')), /public_housing \(Victoria\) on 2025-06-30: the value "n\/a" is not a number or one of the codes \.\., na, np, -/);
plainCase('codes: np and a plain hyphen are accepted as codes', () => {
  sh(shRow('2025-06-30', 'indigenous_community_housing', 'Victoria'), (l) => setValue(l, 'np'));
  sh(shRow('2024-06-30', 'indigenous_community_housing', 'Victoria'), (l) => setValue(l, '-'));
  const r = shRun();
  return check('np and hyphen', !/value "/.test(r.out), r.out) && check('np and hyphen revision', /blocks|changed between "\d+" and "np"/.test(r.out) || r.code !== 0, r.out);
});
failCase('codes: a figure turning into a code is a revision that blocks', () => sh(shRow('2025-06-30', 'public_housing', 'Victoria'), (l) => setValue(l, 'na')), /public_housing \(Victoria\) on 2025-06-30 \(2025\) was 64277 when last accepted and is now na \(a figure or code changed between "64277" and "na"\)/);
failCase('codes: a code turning into a figure is a revision that blocks', () => sh(shRow('2025-06-30', 'somih', 'Victoria'), (l) => setValue(l, '5')), /somih \(Victoria\) on 2025-06-30 \(2025\) was \.\. when last accepted and is now 5/);
failCase('codes: a missing year is still caught when the neighbours are codes', () => sh(shRow('2022-06-30', 'somih', 'Victoria'), () => null), /somih \(Victoria\) is missing 2022-06-30; the rows jump from 2021-06-30 to 2023-06-30/);
failCase('revision: one past public housing count changed by 5 per cent blocks', () => sh(shRow('2020-06-30', 'public_housing', 'Australia'), (l) => setValue(l, String(Math.round(Number(l.split(',')[4]) * 1.05)))),
  /public_housing \(Australia\) on 2020-06-30 \(2020\) was 300403 when last accepted and is now 315423, a change of \+15020 \(the change is more than 1 and more than 2 per cent\)/);
plainCase('revision: a 1 per cent change to a dwelling count passes with a warning', () => {
  sh(shRow('2020-06-30', 'public_housing', 'Australia'), (l) => setValue(l, String(Math.round(Number(l.split(',')[4]) * 1.01))));
  const r = shRun();
  return check('1 per cent', r.code === 0 && /WARNING: metrics\/social-housing\/data\.csv: data has changed since it was last accepted \(1 accepted figure revised/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('revision: a population figure changed by 2 per cent blocks (tolerance 1 per cent)', () => sh(shRow('2020-06-30', 'population', 'Australia'), (l) => setValue(l, String(Math.round(Number(l.split(',')[4]) * 1.02)))), /population \(Australia\) on 2020-06-30 .* \(the change is more than 1 and more than 1 per cent\)/);
failCase('derived sum: a part that is not in the series list', () => editFile(shYml(), (t) => t.replace('from: [public_housing, community_housing, somih, indigenous_community_housing]', 'from: [public_housing, community_housing, somih, nonesuch]')), /series "total_social_housing" is worked out from "nonesuch", which is not in the "series" list/);
failCase('derived sum: a sum of one series', () => editFile(shYml(), (t) => t.replace('from: [public_housing, community_housing, somih, indigenous_community_housing]', 'from: [public_housing]')), /series "total_social_housing" has a "derive" of type sum whose "from" is not a list of at least two series ids/);
failCase('derived ratio: no unit', () => editFile(shYml(), (t) => t.replace(', unit: rate}', '}')), /series "per_1000_people" has a "derive" of type ratio with no "unit"/);
failCase('derived ratio: a factor that is not a whole number', () => editFile(shYml(), (t) => t.replace('factor: 1000', 'factor: 0.5')), /"derive" "factor" that is not a whole number above zero/);
failCase('derived ratio: a field the checker does not know', () => editFile(shYml(), (t) => t.replace('factor: 1000', 'factor: 1000, scale: 2')), /"derive" field "scale" that the checker does not know for type ratio/);
failCase('derived: sum and ratio on different frequencies', () => editFile(shYml(), (t) => t.replace('    derive: {type: ratio, numerator: total_social_housing, denominator: population, factor: 1000, decimals: 1, unit: rate}\n    frequency: annual', '    derive: {type: ratio, numerator: total_social_housing, denominator: population, factor: 1000, decimals: 1, unit: rate}\n    frequency: monthly')), /series "per_1000_people" says it is monthly but "total_social_housing", which it is worked out from, is annual/);
failCase('derived: the worked-out rate outside its plausible range', () => sh(shRow('2025-06-30', 'population', 'Northern Territory'), (l) => setValue(l, '1000')), /per_1000_people \(Northern Territory\) on 2025-06-30, worked out from total_social_housing 12808 and population 1000 on 2025-06-30, is 12808, outside the plausible range 0 to 200/);
failCase('derived: a derived series must not be stored (sum)', () => editFile(dataPath(SH), (t) => t + '2025-06-30,2025,total_social_housing,Australia,450607,count,actual\n'), /series "total_social_housing" is derived in metric\.yml, so it must not have rows in data\.csv/);
failCase('derived: the worked-out total outside its plausible range', () => editFile(shYml(), (t) => t.replace('  - id: total_social_housing\n', '  - id: total_social_housing\n    TMP: 1\n').replace('    TMP: 1\n', '').replace(/(id: total_social_housing[\s\S]*?plausible: )\{min: 0, max: 1000000\}/, '$1{min: 0, max: 400000}')), /total_social_housing \(Australia\) on 2025-06-30, worked out from public_housing 296541 \+ community_housing 118425 \+ somih 17163 \+ indigenous_community_housing 18478 on 2025-06-30, is 450607, outside the plausible range 0 to 400000/);
failCase('panel: an extra column naming a series that is not declared', () => editFile(shYml(), (t) => t.replace('{header: Dwellings (worked out), series: total_social_housing}', '{header: Dwellings (worked out), series: nonesuch}')), /"extra_columns" that is not a list of \{header, series\}/);
failCase('panel: a date_format that is not known', () => editFile(shYml(), (t) => t.replace('date_format: period', 'date_format: weekly')), /a "date_format" that is not period or month_year/);
failCase('panel: the panel series (derived) has no figures for a place', () => editFile(shYml(), (t) => t.replace('national: Australia\n  national_label', 'national: Atlantis\n  national_label')), /the state panel needs per_1000_people for "Atlantis", but data\.csv has no rows for it/);
failCase('panel: a year missing from the derived rate (population removed for one state) does not hide a real gap', () => sh(shRow('2022-06-30', 'population', 'Tasmania'), () => null), /population \(Tasmania\) is missing 2022-06-30/);
failCase('manifest: the edition note is not a map of period to edition', () => editFile(join(work, 'metrics', SH, 'sources', 'manifest.json'), (t) => t.replace(/"rogs-editions": \{[\s\S]*?\n  \}/, '"rogs-editions": {\n    "editions": {}\n  }')), /the entry for "rogs-editions" has "editions" that is not a non-empty map of period to edition/);
plainCase('manifest: the edition note is accepted and is not treated as a file', () => {
  const r = shRun();
  return check('editions note', r.code === 0 && !/rogs-editions/.test(r.out) && /"rogs-editions"/.test(readText(join(work, 'metrics', SH, 'sources', 'manifest.json'))), r.out);
});

// ---- hospital waits: the days unit, the per-series decimals setting, a fixed panel scale, an extra column after the figure
const HW = 'hospital-waits';
const hwRow = (date, series, jur) => (l) => l.startsWith(`${date},`) && l.includes(`,${series},${jur},`);
const hw = (match, fn) => editRows(match, fn, HW);
const hwYml = () => ymlPath(HW);
plainCase('hospital waits: the clean copy passes, with na codes and the days unit', () => {
  const r = run();
  const t = readText(dataPath(HW));
  return check('hw clean', r.code === 0 && /PASS hospital-waits: 360 rows, 4 series, 2016-06-30 to 2025-06-30/.test(r.out)
    && /2016-06-30,2015-16,ed_seen_on_time,Australian Capital Territory,na,pct,actual/.test(t) && /,surgery_median_days,Australia,45,days,actual/.test(t), `exit ${r.code}\n${r.out}`);
});
failCase('hospital waits: one past Australian seen-on-time figure changed by 2 points blocks', () => hw(hwRow('2020-06-30', 'ed_seen_on_time', 'Australia'), (l) => setValue(l, '76')),
  /ed_seen_on_time \(Australia\) on 2020-06-30 \(2019-20\) was 74 when last accepted and is now 76, a change of \+2 \(the change is more than 1\)/);
plainCase('hospital waits: a change of 1 point passes with a warning', () => {
  hw(hwRow('2020-06-30', 'ed_seen_on_time', 'Australia'), (l) => setValue(l, '75'));
  const r = run();
  return check('1 point', r.code === 0 && /WARNING: metrics\/hospital-waits\/data\.csv: data has changed since it was last accepted \(1 accepted figure revised/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('hospital waits: a median wait changed by 3 days blocks (tolerance 2 days)', () => hw(hwRow('2021-06-30', 'surgery_median_days', 'Australia'), (l) => setValue(l, '51')), /surgery_median_days \(Australia\) on 2021-06-30 \(2020-21\) was 48 when last accepted and is now 51, a change of \+3 \(the change is more than 2\)/);
plainCase('hospital waits: a change of 2 days passes with a warning', () => {
  hw(hwRow('2021-06-30', 'surgery_median_days', 'Australia'), (l) => setValue(l, '50'));
  const r = run();
  return check('2 days', r.code === 0 && /WARNING: metrics\/hospital-waits\/data\.csv: data has changed since it was last accepted/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('hospital waits: a figure turning into a code is a revision that blocks', () => hw(hwRow('2024-06-30', 'surgery_median_days', 'Northern Territory'), (l) => setValue(l, '30')), /surgery_median_days \(Northern Territory\) on 2024-06-30 \(2023-24\) was na when last accepted and is now 30/);
failCase('hospital waits: days outside the plausible range', () => hw(hwRow('2025-06-30', 'surgery_90th_days', 'Tasmania'), (l) => setValue(l, '1200')), /surgery_90th_days \(Tasmania\) on 2025-06-30 is 1200, outside the plausible range 0 to 1000/);
failCase('hospital waits: a per cent over 100', () => hw(hwRow('2025-06-30', 'ed_within_4_hours', 'Victoria'), (l) => setValue(l, '152.7')), /ed_within_4_hours \(Victoria\) on 2025-06-30 is 152\.7, outside the plausible range 0 to 100/);
failCase('hospital waits: a series with two units (one row in days)', () => hw(hwRow('2025-06-30', 'surgery_median_days', 'Victoria'), (l) => { const c = l.split(','); c[5] = 'count'; return c.join(','); }), /series "surgery_median_days" has more than one unit \(days, count\)/);
failCase('hospital waits: a missing financial year', () => hw(hwRow('2022-06-30', 'surgery_90th_days', 'Australia'), () => null), /surgery_90th_days \(Australia\) is missing 2022-06-30; the rows jump from 2021-06-30 to 2023-06-30/);
failCase('decimals: a stored figure with a decimal the page would not show', () => hw(hwRow('2025-06-30', 'ed_seen_on_time', 'Australia'), (l) => setValue(l, '67.4')), /ed_seen_on_time \(Australia\) on 2025-06-30 is 67\.4, which has more decimal places than the 0 the page shows for this series \("decimals" in metric\.yml\)/);
failCase('decimals: two decimals where the page shows one', () => hw(hwRow('2025-06-30', 'ed_within_4_hours', 'Australia'), (l) => setValue(l, '53.45')), /ed_within_4_hours \(Australia\) on 2025-06-30 is 53\.45, which has more decimal places than the 1 the page shows/);
failCase('decimals: a setting that is not a whole number from 0 to 3', () => editFile(hwYml(), (t) => t.replace('decimals: 1', 'decimals: 5')), /series "ed_within_4_hours" has a "decimals" that is not a whole number from 0 to 3/);
failCase('decimals: a setting that is text', () => editFile(hwYml(), (t) => t.replace('decimals: 0', 'decimals: none')), /series "ed_seen_on_time" has a "decimals" that is not a whole number from 0 to 3/);
failCase('panel: a fixed scale that is not min below max', () => editFile(hwYml(), (t) => t.replace('y_range: {min: 0, max: 100}', 'y_range: {min: 100, max: 0}')), /"state_panel_config" has a "y_range" that is not \{min: <number>, max: <larger number>\}/);
failCase('panel: a figure outside the fixed scale', () => editFile(hwYml(), (t) => t.replace('y_range: {min: 0, max: 100}', 'y_range: {min: 0, max: 70}')), /the state panel scale is fixed at 0 to 70 \("y_range"\), but ed_seen_on_time for "[A-Za-z ]+" on 20\d\d-06-30 is \d+, outside it/);
failCase('panel: an extra column whose "after" is not true or false', () => editFile(hwYml(), (t) => t.replace('after: true}', 'after: later}')), /"extra_columns" that is not a list of \{header, series\} \(and optionally after: true/);
plainCase('panel: the fixed scale and the extra column after the figure are accepted', () => {
  const r = run();
  return check('scale and after', r.code === 0 && /y_range/.test(readText(hwYml())) && /after: true/.test(readText(hwYml())), r.out);
});

// ---- homelessness: the census frequency, the per_day unit, two tables, extra panel columns with their own latest figure
const HL = 'homelessness';
const hlRow = (date, series, jur) => (l) => l.startsWith(`${date},`) && l.includes(`,${series},${jur},`);
const hl = (match, fn) => editRows(match, fn, HL);
const hlYml = () => ymlPath(HL);
plainCase('homelessness: the clean copy passes, with Census dates, the per_day unit and a plain zero', () => {
  const r = run();
  const t = readText(dataPath(HL));
  return check('hl clean', r.code === 0 && /PASS homelessness: 279 rows, 7 series, 2011-08-09 to 2025-06-30/.test(r.out)
    && /^2021-08-10,2021,census_homeless_number,Australia,122494,count,actual$/m.test(t) && /^2016-08-09,2016,census_homeless_rate,Australia,49\.8,rate,actual$/m.test(t)
    && /^2025-06-30,2024-25,unassisted_accommodation_daily,Australia,232\.0,per_day,actual$/m.test(t) && /,unassisted_no_need_daily,South Australia,0,per_day,actual/.test(t), `exit ${r.code}\n${r.out}`);
});
failCase('census: a Census missing between two others', () => hl(hlRow('2016-08-09', 'census_homeless_rate', 'Australia'), () => null), /census_homeless_rate \(Australia\) is missing 2016-08-09; the rows jump from 2011-08-09 to 2021-08-10/);
failCase('census: a Census night ten days off its five-year schedule', () => hl(hlRow('2016-08-09', 'census_homeless_number', 'Victoria'), (l) => l.replace('2016-08-09', '2016-08-19')), /census_homeless_number \(Victoria\) has a row on 2016-08-19 \(line \d+\) which is not on the census schedule after 2011-08-09; expected 2016-08-09/);
failCase('census: a Census held after a gap of ten years', () => hl((l) => l.startsWith('2016-08-09,'), () => null), /census_homeless_(rate|number) \([A-Za-z ]+\) is missing 2016-08-09; the rows jump from 2011-08-09 to 2021-08-10/);
plainCase('census: a Census night a few days either side of the same day five years on is accepted', () => {
  hl((l) => l.startsWith('2016-08-09,'), (l) => l.replace('2016-08-09', '2016-08-12'));
  const r = run('--accept');
  return check('census tolerance', r.code === 0 && !/census schedule|is missing/.test(r.out) && /Accepted metrics\/homelessness\/data\.csv/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('census: a series on the census frequency may not be called annual by mistake (annual needs exactly one year)', () => editFile(hlYml(), (t) => t.replace('id: census_homeless_number\n    label: People who are homeless, number\n    definition: People counted as homeless on Census night (all homelessness operational groups, total). Count of people.\n    source_table: Productivity Commission, Report on Government Services, table 19A.2 (ABS Census of Population and Housing - estimating homelessness), Number, Total\n    frequency: census', 'id: census_homeless_number\n    label: People who are homeless, number\n    definition: People counted as homeless on Census night (all homelessness operational groups, total). Count of people.\n    source_table: Productivity Commission, Report on Government Services, table 19A.2 (ABS Census of Population and Housing - estimating homelessness), Number, Total\n    frequency: annual')), /census_homeless_number \(Australia\) is missing 2012-08-09/);
failCase('census: an unknown frequency is still refused', () => editFile(hlYml(), (t) => t.replace('frequency: census', 'frequency: decennial')), /has frequency "decennial", which the validator does not know\. Known: annual, monthly, quarterly, census/);
failCase('homelessness: the Census rate changed by 0.5 blocks (tolerance 0.1)', () => hl(hlRow('2016-08-09', 'census_homeless_rate', 'Australia'), (l) => setValue(l, '50.3')), /census_homeless_rate \(Australia\) on 2016-08-09 \(2016\) was 49\.8 when last accepted and is now 50\.3, a change of \+0\.5 \(the change is more than 0\.1\)/);
plainCase('homelessness: a Census rate change of 0.1 passes with a warning', () => {
  hl(hlRow('2016-08-09', 'census_homeless_rate', 'Australia'), (l) => setValue(l, '49.9'));
  const r = run();
  return check('rate 0.1', r.code === 0 && /WARNING: metrics\/homelessness\/data\.csv: data has changed since it was last accepted/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('homelessness: a Census count changed by 2 blocks (tolerance 1)', () => hl(hlRow('2021-08-10', 'census_homeless_number', 'Australia'), (l) => setValue(l, '122496')), /census_homeless_number \(Australia\) on 2021-08-10 \(2021\) was 122494 when last accepted and is now 122496, a change of \+2 \(the change is more than 1\)/);
failCase('homelessness: clients changed by more than 1 per cent blocks', () => hl(hlRow('2025-06-30', 'clients', 'Australia'), (l) => setValue(l, '300000')), /clients \(Australia\) on 2025-06-30 \(2024-25\) was 288970 when last accepted and is now 300000/);
plainCase('homelessness: clients changed by less than 1 per cent passes with a warning', () => {
  hl(hlRow('2025-06-30', 'clients', 'Australia'), (l) => setValue(l, '289100'));
  const r = run();
  return check('clients small', r.code === 0 && /WARNING: metrics\/homelessness\/data\.csv: data has changed since it was last accepted/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('homelessness: the unmet-need per cent changed by 0.8 blocks (tolerance 0.5)', () => hl(hlRow('2025-06-30', 'unmet_accommodation_pct', 'Australia'), (l) => setValue(l, '34.0')), /unmet_accommodation_pct \(Australia\) on 2025-06-30 \(2024-25\) was 33\.2 when last accepted and is now 34\.0/);
failCase('homelessness: requests a day changed by 1.5 blocks (tolerance 1)', () => hl(hlRow('2025-06-30', 'unassisted_other_daily', 'Australia'), (l) => setValue(l, '80.9')), /unassisted_other_daily \(Australia\) on 2025-06-30 \(2024-25\) was 79\.4 when last accepted and is now 80\.9/);
plainCase('homelessness: requests a day changed by 0.9 passes with a warning', () => {
  hl(hlRow('2025-06-30', 'unassisted_other_daily', 'Australia'), (l) => setValue(l, '80.3'));
  const r = run();
  return check('per day small', r.code === 0 && /WARNING: metrics\/homelessness\/data\.csv: data has changed since it was last accepted/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('homelessness: a Census rate over the plausible range', () => hl(hlRow('2021-08-10', 'census_homeless_rate', 'Northern Territory'), (l) => setValue(l, '1500.0')), /census_homeless_rate \(Northern Territory\) on 2021-08-10 is 1500, outside the plausible range 0 to 1000/);
failCase('homelessness: requests a day over the plausible range', () => hl(hlRow('2025-06-30', 'unassisted_accommodation_daily', 'Australia'), (l) => setValue(l, '5200.0')), /unassisted_accommodation_daily \(Australia\) on 2025-06-30 is 5200, outside the plausible range 0 to 5000/);
failCase('homelessness: a per_day figure given the rate unit', () => hl(hlRow('2025-06-30', 'unassisted_other_daily', 'Victoria'), (l) => { const c = l.split(','); c[5] = 'rate'; return c.join(','); }), /series "unassisted_other_daily" has more than one unit \(per_day, rate\)/);
failCase('homelessness: the worked-out total of requests a day outside its plausible range', () => editFile(hlYml(), (t) => t.replace(/(id: unassisted_daily_total[\s\S]*?plausible: )\{min: 0, max: 5000\}/, '$1{min: 0, max: 300}')), /unassisted_daily_total \(Australia\) on 2025-06-30, worked out from unassisted_accommodation_daily 232\.0 \+ unassisted_other_daily 79\.4 \+ unassisted_no_need_daily 41\.7 on 2025-06-30, is 353\.1, outside the plausible range 0 to 300/);
failCase('homelessness: the worked-out total must not be stored', () => editFile(dataPath(HL), (t) => t + '2025-06-30,2024-25,unassisted_daily_total,Australia,353.1,per_day,actual\n'), /series "unassisted_daily_total" is derived in metric\.yml, so it must not have rows in data\.csv/);
failCase('tables: a list of tables whose second table names a series that is not declared', () => editFile(hlYml(), (t) => t.replace('series: unassisted_daily_total\n        jurisdiction: Australia\n\nmeaning', 'series: nonesuch\n        jurisdiction: Australia\n\nmeaning')), /nonesuch/);
failCase('tables: a table that is not a table or a list of tables', () => editFile(hlYml(), (t) => t.replace(/\ntable:\n[\s\S]*?\nmeaning:/, '\ntable: 5\n\nmeaning:')), /"table" must be one table or a list of tables/);
failCase('tables: a table with no columns', () => editFile(hlYml(), (t) => t.replace('  - period_header: Census\n    columns:', '  - period_header: Census\n    columnz:')), /a table has no "columns"/);
failCase('tables: a series with several jurisdictions used in a table without naming one', () => editFile(hlYml(), (t) => t.replace('      - header: "Homeless (number)"\n        series: census_homeless_number\n        jurisdiction: Australia', '      - header: "Homeless (number)"\n        series: census_homeless_number')), /the table uses series "census_homeless_number", which has figures for 9 jurisdictions .* Name one with "jurisdiction:"/);
failCase('panel: with_period needs own_latest', () => editFile(hlYml(), (t) => t.replace('after: true, own_latest: true, with_period: true}', 'after: true, with_period: true}')), /"extra_columns" that is not a list of \{header, series\}/);
failCase('panel: own_latest that is not true or false', () => editFile(hlYml(), (t) => t.replace('own_latest: true, with_period: true}', 'own_latest: yes please, with_period: true}')), /"extra_columns" that is not a list of \{header, series\}/);
failCase('panel: an own-latest column for a place with no figure', () => hl((l) => l.includes(',clients,Tasmania,'), () => null), /the state panel column "Clients helped, latest year" shows the latest clients for each place, but "Tasmania" has no figure for it/);
failCase('panel: markers that is not true or false', () => editFile(hlYml(), (t) => t.replace('\n  markers: true\n  extra_columns', '\n  markers: sometimes\n  extra_columns')), /"state_panel_config" has a "markers" that is not true or false/);
failCase('panel: a figure above the fixed scale (the Northern Territory in 2011 is 723.7)', () => editFile(hlYml(), (t) => t.replace('y_range: {min: 0, max: 800}', 'y_range: {min: 0, max: 700}')), /the state panel scale is fixed at 0 to 700 \("y_range"\), but census_homeless_rate for "Northern Territory" on 2011-08-09 is 723\.7, outside it/);
failCase('panel: the places end on different Censuses', () => hl((l) => l.includes(',census_homeless_rate,Tasmania,') && l.startsWith('2021-08-10'), () => null), /the places in the state panel do not all end on the same date/);
failCase('views: markers that is not true or false', () => editFile(hlYml(), (t) => t.replace('    markers: true\n    lines:', '    markers: 1\n    lines:')), /view "census" has a "markers" that is not true or false/);
failCase('the per_day unit is refused if format.ts cannot format it', () => editFile(p('src', 'lib', 'format.ts'), (t) => t.replaceAll("unit === 'per_day'", "unit === 'perday'")), /src\/lib\/format\.ts: formats the units .* but scripts\/validate\.mjs lists/);

// ---- derive.mjs directly: sums, ratios, codes, chained series
plainCase('sumText adds exactly, counts .. and - as zero and blanks on na or np', () => {
  const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  return check('sum plain', eq(sumText(['92709', '17163', '118425', '18478']), { text: '246775' }), 'plain sum')
    && check('sum codes zero', eq(sumText(['5', '..', '-', '7']), { text: '12' }), 'zero codes')
    && check('sum all zero codes', eq(sumText(['..', '..']), { text: '0' }), 'all zero')
    && check('sum na', sumText(['5', 'na']).blank?.includes('na'), 'na blanks')
    && check('sum np beats zero codes', sumText(['..', 'np', '3']).blank?.includes('np'), 'np blanks')
    && check('sum decimals exact', eq(sumText(['0.1', '0.2']), { text: '0.3' }), 'decimals')
    && check('sum mixed scales', eq(sumText(['1.5', '2']), { text: '3.5' }), 'scales')
    && check('sum junk', sumText(['5', 'x']).blank !== undefined, 'junk is blank, never guessed');
});
plainCase('ratioText rounds half up to the places asked and blanks on codes or a zero denominator', () => {
  const t = (...a) => ratioText(...a);
  return check('ratio real', t('450607', '27601739', 1000, 1).text === '16.3', 'Australia 2025')
    && check('ratio half up', t('1', '8', 1000, 1).text === '125.0' && t('5', '16000', 1000, 1).text === '0.3' && t('1', '16000', 1000, 1).text === '0.1', 'ties go up')
    && check('ratio tie exact', t('25', '1000', 1, 1).text === '0.0', 'no floating point')
    && check('ratio 0.05 tie', t('1', '2000', 100, 1).text === '0.1', '0.05 rounds up to 0.1')
    && check('ratio negative tie away from zero', t('-1', '2000', 100, 1).text === '-0.1', 'negative tie')
    && check('ratio zero places', t('3', '2', 1, 0).text === '2' && t('1', '3', 1, 0).text === '0', 'no decimals')
    && check('ratio code numerator', t('na', '5', 1000, 1).blank?.includes('numerator is na'), 'code')
    && check('ratio code denominator', t('5', '..', 1000, 1).blank?.includes('denominator is ..'), 'code')
    && check('ratio zero denominator', t('5', '0', 1000, 1).blank !== undefined, 'zero')
    && check('isValueCode', isValueCode('..') && isValueCode('na') && isValueCode('np') && isValueCode('-') && !isValueCode('0') && !isValueCode('-1'), 'codes');
});
plainCase('computeDerived chains a sum into a ratio, leaves blanks out and says why', () => {
  const stored = new Map();
  const put = (id, j, rows) => stored.set(`${id}|${j}`, rows.map(([date, v]) => ({ date, period: date.slice(0, 4), valueText: v, unit: 'count' })));
  put('a', 'X', [['2024-06-30', '10'], ['2025-06-30', '12']]);
  put('b', 'X', [['2024-06-30', '..'], ['2025-06-30', 'na']]);
  put('pop', 'X', [['2024-06-30', '1000'], ['2025-06-30', '1000']]);
  put('a', 'Y', [['2024-06-30', '5']]);
  put('b', 'Y', [['2024-06-30', '5'], ['2025-06-30', '5']]);
  put('pop', 'Y', [['2024-06-30', '100'], ['2025-06-30', '100']]);
  const series = [
    { id: 'a' }, { id: 'b' }, { id: 'pop' },
    { id: 'rate', derive: { type: 'ratio', numerator: 'total', denominator: 'pop', factor: 1000, decimals: 1, unit: 'rate' } }, // declared before its input on purpose
    { id: 'total', derive: { type: 'sum', from: ['a', 'b'] } },
  ];
  const out = computeDerived(series, stored);
  const rows = (k) => (out.groups.get(k) ?? []).map((r) => `${r.date}=${r.valueText}${r.unit}`).join(' ');
  return check('derive total X', rows('total|X') === '2024-06-30=10count', rows('total|X'))
    && check('derive rate X', rows('rate|X') === '2024-06-30=10.0rate', rows('rate|X'))
    && check('derive total Y (2025 missing a)', rows('total|Y') === '2024-06-30=10count', rows('total|Y'))
    && check('derive rate Y', rows('rate|Y') === '2024-06-30=100.0rate', rows('rate|Y'))
    && check('blank reasons', out.blanks.some((b) => b.series === 'total' && b.jurisdiction === 'X' && b.date === '2025-06-30' && /na/.test(b.reason)) && out.blanks.some((b) => b.series === 'total' && b.jurisdiction === 'Y' && /a has no figure for 2025-06-30/.test(b.reason)), JSON.stringify(out.blanks))
    && check('no problems', out.problems.length === 0, out.problems.join('; '));
});
plainCase('computeDerived refuses a loop, an unknown input and mixed units', () => {
  const stored = new Map([['a|X', [{ date: '2024-06-30', period: '2024', valueText: '1', unit: 'count' }]], ['p|X', [{ date: '2024-06-30', period: '2024', valueText: '1', unit: 'pct' }]]]);
  const loop = computeDerived([{ id: 'a' }, { id: 'u', derive: { type: 'sum', from: ['v', 'a'] } }, { id: 'v', derive: { type: 'sum', from: ['u', 'a'] } }], stored);
  const unknown = computeDerived([{ id: 'a' }, { id: 'u', derive: { type: 'sum', from: ['a', 'zz'] } }], stored);
  const mixed = computeDerived([{ id: 'a' }, { id: 'p' }, { id: 'u', derive: { type: 'sum', from: ['a', 'p'] } }], stored);
  return check('loop', loop.problems.some((m) => /worked out from itself/.test(m)), loop.problems.join(';'))
    && check('unknown', unknown.problems.some((m) => /"zz", which is not in the "series" list/.test(m)), unknown.problems.join(';'))
    && check('mixed', mixed.problems.some((m) => /different units \(count, pct\)/.test(m)), mixed.problems.join(';'));
});


// ---- new homes: cumulative_sum, straight_line and a ratio with a fixed denominator date; reference lines, dashed lines, the axis end and the status block
const NH = 'new-homes';
const nhRow = (date, series, jur) => (l) => l.startsWith(`${date},`) && l.includes(`,${series},${jur},`);
const nh = (match, fn) => editRows(match, fn, NH);
const nhYml = () => ymlPath(NH);
plainCase('new homes: the clean copy passes', () => {
  const r = run();
  return check('nh clean', r.code === 0 && /PASS new-homes: 1521 rows, 2 series, 1984-09-30 to 2026-06-30/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('new homes: a past Australia quarter changed by 5 per cent blocks (tolerance 3 per cent)', () => nh(nhRow('2025-03-31', 'completions', 'Australia'), (l) => setValue(l, String(Math.round(Number(l.split(',')[4]) * 1.05)))),
  /completions \(Australia\) on 2025-03-31 \(2025-Q1\) was \d+ when last accepted and is now \d+, a change of \+\d+ \(the change is more than 1 and more than 3 per cent\)/);
plainCase('new homes: a 2 per cent change to a past quarter passes with a warning', () => {
  nh(nhRow('2025-03-31', 'completions', 'Australia'), (l) => setValue(l, String(Math.round(Number(l.split(',')[4]) * 1.02))));
  const r = run();
  return check('2 per cent', r.code === 0 && /WARNING: metrics\/new-homes\/data\.csv: data has changed since it was last accepted \(1 accepted figure revised/.test(r.out), `exit ${r.code}\n${r.out}`);
});
failCase('new homes: a population row that differs from the social housing page blocks (copy_of)', () => nh(nhRow('2024-06-30', 'population_june_2024', 'Victoria'), (l) => setValue(l, String(Number(l.split(',')[4]) + 1))),
  /new-homes\/data\.csv: line \d+, population_june_2024 \(Victoria\) on 2024-06-30 is \d+ \(count\), but the social-housing page's population for that date is \d+\. population_june_2024 must equal population on the social-housing page/);
failCase('new homes: the social housing population changes and the copy does not', () => editRows(nhRow('2024-06-30', 'population', 'Australia'), (l) => setValue(l, String(Number(l.split(',')[4]) + 1)), SH),
  /population_june_2024 \(Australia\) on 2024-06-30 is \d+ \(count\), but the social-housing page's population for that date is \d+/);
failCase('new homes: the population has no row on the social housing page', () => editRows(nhRow('2024-06-30', 'population', 'Tasmania'), () => null, SH), /population_june_2024 \(Tasmania\) on 2024-06-30 .*but metrics\/social-housing\/data\.csv has no population row for 2024-06-30/);
failCase('new homes: a quarter missing inside a state', () => nh(nhRow('2025-03-31', 'completions', 'Victoria'), () => null), /completions \(Victoria\) is missing 2025-03-31; the rows jump from 2024-12-31 to 2025-06-30/);
failCase('new homes: a quarter dated off the quarter end', () => nh(nhRow('2025-03-31', 'completions', 'Australia'), (l) => l.replace('2025-03-31', '2025-03-30')), /completions \(Australia\) on 2025-03-30 is not the last day of March, June, September or December/);
failCase('new homes: a completions figure outside the plausible range', () => nh(nhRow('2025-03-31', 'completions', 'Australia'), (l) => setValue(l, '100001')), /completions \(Australia\) on 2025-03-31 is 100001, outside the plausible range 0 to 100000/);
failCase('new homes: the population missing for a state (rows fall against the lock)', () => nh(nhRow('2024-06-30', 'population_june_2024', 'Tasmania'), () => null), /population_june_2024 \(Tasmania\) had 1 rows when the data was last accepted but has none now/);
failCase('new homes: a worked-out running total outside its plausible range', () => editFile(nhYml(), (t) => t.replace('plausible: {min: 0, max: 1500000}', 'plausible: {min: 0, max: 1000}')), /accord_completed \(Australia\) on 2024-09-30, worked out from the running total of completions from 2024-09-30 to 2024-09-30, is \d+, outside the plausible range 0 to 1000/);
failCase('new homes: the straight-line pace outside its plausible range', () => editFile(nhYml(), (t) => t.replace('plausible: {min: 0, max: 1200000}', 'plausible: {min: 0, max: 1000000}')), /pace_line \(Australia\) on 2029-06-30, worked out from a straight line from 0 on 2024-06-30 to 1200000 on 2029-06-30, 20 of 20 periods, is 1200000, outside the plausible range 0 to 1000000/);
failCase('new homes: a derived series stored in data.csv (cumulative)', () => editFile(dataPath(NH), (t) => t + '2026-06-30,2026-Q2,accord_completed,Australia,355817,count,actual\n'), /series "accord_completed" is derived in metric\.yml, so it must not have rows in data\.csv/);
failCase('derive: cumulative_sum start that is not the last day of a quarter', () => editFile(nhYml(), (t) => t.replace('start: 2024-09-30}', 'start: 2024-09-29}')), /series "accord_completed" has a "derive" "start" that is not a real date|starts its running total on 2024-09-29, which is not the last day of a quarter/);
failCase('derive: cumulative_sum start is not a date', () => editFile(nhYml(), (t) => t.replace('start: 2024-09-30}', 'start: September}')), /series "accord_completed" has a "derive" "start" that is not a real date written YYYY-MM-DD/);
failCase('derive: cumulative_sum from a series that is not there', () => editFile(nhYml(), (t) => t.replace('type: cumulative_sum, from: completions', 'type: cumulative_sum, from: nonesuch')), /series "accord_completed" is worked out from "nonesuch", which is not in the "series" list/);
failCase('derive: straight_line with an end date before the start', () => editFile(nhYml(), (t) => t.replace('end: {date: 2029-06-30, value: 1200000}', 'end: {date: 2023-06-30, value: 1200000}')), /series "pace_line" has a "derive" whose "end" date is not after its "start" date/);
failCase('derive: straight_line dates that are not quarter ends', () => editFile(nhYml(), (t) => t.replace('start: {date: 2024-06-30, value: 0}', 'start: {date: 2024-07-01, value: 0}')), /series "pace_line" has a "derive" "start" date 2024-07-01, which is not the last day of a quarter/);
failCase('derive: straight_line with no jurisdiction', () => editFile(nhYml(), (t) => t.replace(', jurisdiction: Australia, unit: count}', ', unit: count}')), /series "pace_line" has a "derive" of type straight_line with no "jurisdiction"/);
failCase('derive: straight_line with a value that is not a number', () => editFile(nhYml(), (t) => t.replace('value: 1200000}, jurisdiction', 'value: lots}, jurisdiction')), /series "pace_line" has a "derive" "end" with a "value" that is not a plain number/);
failCase('derive: straight_line with a field the checker does not know', () => editFile(nhYml(), (t) => t.replace(', jurisdiction: Australia, unit: count}', ', jurisdiction: Australia, unit: count, curve: 2}')), /series "pace_line" has a "derive" field "curve" that the checker does not know for type straight_line/);
failCase('derive: ratio with a denominator_date that is not a date', () => editFile(nhYml(), (t) => t.replace('denominator_date: 2024-06-30', 'denominator_date: June')), /series "accord_per_1000" has a "derive" "denominator_date" that is not a real date written YYYY-MM-DD/);
failCase('derive: ratio with a fixed denominator date is still checked for the numerator frequency', () => editFile(nhYml(), (t) => t.replace('    frequency: quarterly\n    plausible: {min: 0, max: 100}', '    frequency: monthly\n    plausible: {min: 0, max: 100}')), /series "accord_per_1000" says it is monthly but "accord_completed", which it is worked out from, is quarterly/);
failCase('view: a reference line with a style that is not solid or dashed', () => editFile(nhYml(), (t) => t.replace('style: solid}', 'style: red}')), /view "accord" has a reference line whose "style" is not solid or dashed/);
failCase('view: a reference line with no label', () => editFile(nhYml(), (t) => t.replace('label: "Original target: 1 million (set October 2022)", ', 'label: "", ')), /view "accord" has a reference line with no "label"/);
failCase('view: a reference line whose value is not a number', () => editFile(nhYml(), (t) => t.replace('value: 1000000,', 'value: lots,')), /view "accord" has a reference line whose "value" is not a number/);
failCase('view: a reference line with a field the checker does not know', () => editFile(nhYml(), (t) => t.replace('style: dashed}', 'style: dashed, colour: red}')), /view "accord" has a reference line that is not \{value, label, style\}/);
failCase('view: reference_lines that is not a list', () => editFile(nhYml(), (t) => t.replace('    reference_lines:\n      - {value: 1200000, label: "Target: 1.2 million by June 2029 (set August 2023)", style: solid}\n      - {value: 1000000, label: "Original target: 1 million (set October 2022)", style: dashed}\n', '    reference_lines: 1200000\n')), /view "accord" has "reference_lines" that is not a list of \{value, label, style\}/);
failCase('view: a "to" that is not a date', () => editFile(nhYml(), (t) => t.replace('to: "2029-06-30"', 'to: "June 2029"')), /view "accord" has a "to" that is not a real date written YYYY-MM-DD/);
failCase('view: a "to" before the "from" year', () => editFile(nhYml(), (t) => t.replace('to: "2029-06-30"', 'to: "2023-06-30"')), /view "accord" has a "to" date that is not after its "from" year/);
failCase('view: a dash that is not true or false', () => editFile(nhYml(), (t) => t.replace('dash: true', 'dash: sometimes')), /view "accord" has a line whose "dash" is not true or false/);
failCase('status: a word that is not one of the five', () => editFile(nhYml(), (t) => t.replace('  status: Behind', '  status: Late')), /status "Late" is not one of Met, On track, Behind, Missed, Too early to say/);
failCase('status: no assessed_by', () => editFile(nhYml(), (t) => t.replace('  assessed_by: "National Housing Supply and Affordability Council"\n', '')), /"status" needs "assessed_by", as text/);
failCase('status: an assessed_on that is not a month or date', () => editFile(nhYml(), (t) => t.replace('assessed_on: "2026-08"', 'assessed_on: "August 2026"')), /"status" needs "assessed_on", a month YYYY-MM or a date YYYY-MM-DD/);
failCase('status: a due date that is not real', () => editFile(nhYml(), (t) => t.replace('due: "2029-06-30"', 'due: "2029-02-30"')), /"status" needs "due", a real date written YYYY-MM-DD/);
failCase('status: a field the checker does not know', () => editFile(nhYml(), (t) => t.replace('  due: "2029-06-30"', '  due: "2029-06-30"\n  rating: amber')), /"status" must be \{status, assessed_by, assessed_on, due\}/);
failCase('status: a status tile with no status block', () => editFile(nhYml(), (t) => t.replace(/status:\n  status: Behind\n  assessed_by: .*\n  assessed_on: .*\n  due: .*\n/, '')), /tile "Target status" has "from_status" but metric\.yml has no "status" block/);
failCase('status: a status tile that also has text', () => editFile(nhYml(), (t) => t.replace('    from_status: true\n', '    from_status: true\n    text: Behind\n')), /tile "Target status" has "from_status" and also "text" or "series"/);
plainCase('derive: cumulative_sum adds from the start date, is blank before it and stops at a gap or an unknown code', () => {
  const put = (rows) => new Map([['c|X', rows.map(([date, v]) => ({ date, period: date.slice(0, 7), valueText: v, unit: 'count' }))]]);
  const series = [{ id: 'c', frequency: 'quarterly' }, { id: 't', frequency: 'quarterly', derive: { type: 'cumulative_sum', from: 'c', start: '2024-09-30' } }];
  const show = (out) => (out.groups.get('t|X') ?? []).map((r) => `${r.date}=${r.valueText}`).join(' ');
  const base = put([['2024-06-30', '5'], ['2024-09-30', '10'], ['2024-12-31', '20'], ['2025-03-31', '30'], ['2025-06-30', '40']]);
  const ok = computeDerived(series, base);
  const gap = computeDerived(series, put([['2024-06-30', '5'], ['2024-09-30', '10'], ['2025-03-31', '30'], ['2025-06-30', '40']]));
  const code = computeDerived(series, put([['2024-09-30', '10'], ['2024-12-31', 'na'], ['2025-03-31', '30']]));
  const zero = computeDerived(series, put([['2024-09-30', '10'], ['2024-12-31', '..'], ['2025-03-31', '30']]));
  const noStart = computeDerived(series, put([['2024-12-31', '20'], ['2025-03-31', '30']]));
  const dec = computeDerived(series, put([['2024-09-30', '0.1'], ['2024-12-31', '0.2']]));
  return check('cumulative ok', show(ok) === '2024-09-30=10 2024-12-31=30 2025-03-31=60 2025-06-30=100' && ok.problems.length === 0, show(ok))
    && check('cumulative gap', show(gap) === '2024-09-30=10' && gap.blanks.some((b) => b.date === '2024-12-31' && /no figure for 2024-12-31/.test(b.reason)), `${show(gap)} ${JSON.stringify(gap.blanks)}`)
    && check('cumulative later dates blank after a gap', gap.blanks.some((b) => b.date === '2025-06-30' && /blank after 2024-12-31/.test(b.reason)), JSON.stringify(gap.blanks))
    && check('cumulative unknown code', show(code) === '2024-09-30=10' && code.blanks.some((b) => b.date === '2024-12-31') && code.blanks.some((b) => b.date === '2025-03-31'), `${show(code)} ${JSON.stringify(code.blanks)}`)
    && check('cumulative zero code', show(zero) === '2024-09-30=10 2024-12-31=10 2025-03-31=40', show(zero))
    && check('cumulative needs the start quarter', show(noStart) === '' && noStart.blanks.some((b) => b.date === '2024-12-31'), `${show(noStart)} ${JSON.stringify(noStart.blanks)}`)
    && check('cumulative exact decimals', show(dec) === '2024-09-30=0.1 2024-12-31=0.3', show(dec));
});
plainCase('derive: straight_line is exact, rounds half away from zero and has one figure per period after the start', () => {
  const mk = (derive, frequency = 'quarterly') => computeDerived([{ id: 'p', frequency, derive: { type: 'straight_line', jurisdiction: 'A', unit: 'count', ...derive } }], new Map());
  const vals = (out) => (out.groups.get('p|A') ?? []).map((r) => `${r.date}=${r.valueText}`).join(' ');
  const target = mk({ start: { date: '2024-06-30', value: 0 }, end: { date: '2029-06-30', value: 1200000 } });
  const rows = target.groups.get('p|A');
  const third = mk({ start: { date: '2024-06-30', value: 0 }, end: { date: '2025-03-31', value: 100 } });
  const down = mk({ start: { date: '2024-06-30', value: 10 }, end: { date: '2025-03-31', value: 0 } });
  const neg = mk({ start: { date: '2024-06-30', value: 0 }, end: { date: '2025-03-31', value: -100 } });
  const dec = mk({ start: { date: '2024-06-30', value: 0 }, end: { date: '2024-12-31', value: 1 }, decimals: 2 });
  const monthly = mk({ start: { date: '2024-01-31', value: 0 }, end: { date: '2024-04-30', value: 3 } }, 'monthly');
  return check('line count', rows.length === 20 && rows[0].date === '2024-09-30' && rows[0].valueText === '60000' && rows[7].date === '2026-06-30' && rows[7].valueText === '480000' && rows[19].date === '2029-06-30' && rows[19].valueText === '1200000', JSON.stringify([rows.length, rows[0], rows[7], rows[19]]))
    && check('line period labels', rows[0].period === '2024-Q3' && rows[19].period === '2029-Q2' && rows[0].unit === 'count', `${rows[0].period} ${rows[19].period}`)
    && check('line third', vals(third) === '2024-09-30=33 2024-12-31=67 2025-03-31=100', vals(third))
    && check('line down', vals(down) === '2024-09-30=7 2024-12-31=3 2025-03-31=0', vals(down))
    && check('line negative rounds away from zero', vals(neg) === '2024-09-30=-33 2024-12-31=-67 2025-03-31=-100', vals(neg))
    && check('line decimals', vals(dec) === '2024-09-30=0.50 2024-12-31=1.00', vals(dec))
    && check('line monthly', vals(monthly) === '2024-02-29=1 2024-03-31=2 2024-04-30=3', vals(monthly))
    && check('line no problems', target.problems.length === 0, target.problems.join(';'));
});
plainCase('derive: a ratio with a fixed denominator date divides every date by the one figure and blanks if it is missing', () => {
  const put = (id, j, rows) => [`${id}|${j}`, rows.map(([date, v]) => ({ date, period: date.slice(0, 7), valueText: v, unit: 'count' }))];
  const stored = new Map([put('n', 'X', [['2024-09-30', '10'], ['2024-12-31', '30']]), put('d', 'X', [['2024-06-30', '2000'], ['2023-06-30', '1']]), put('n', 'Y', [['2024-09-30', '10']]), put('d', 'Y', [['2023-06-30', '5']])]);
  const series = [{ id: 'n', frequency: 'quarterly' }, { id: 'd', frequency: 'annual' }, { id: 'r', frequency: 'quarterly', derive: { type: 'ratio', numerator: 'n', denominator: 'd', denominator_date: '2024-06-30', factor: 1000, decimals: 1, unit: 'rate' } }];
  const out = computeDerived(series, stored);
  const show = (k) => (out.groups.get(k) ?? []).map((r) => `${r.date}=${r.valueText}${r.unit}`).join(' ');
  return check('fixed X', show('r|X') === '2024-09-30=5.0rate 2024-12-31=15.0rate', show('r|X'))
    && check('fixed Y blank', show('r|Y') === '' && out.blanks.some((b) => b.series === 'r' && b.jurisdiction === 'Y' && /d has no figure for 2024-06-30/.test(b.reason)), JSON.stringify(out.blanks))
    && check('fixed derivedFrom', /d 2000 \(d on 2024-06-30\)/.test(out.groups.get('r|X')[0].derivedFrom), out.groups.get('r|X')[0].derivedFrom)
    && check('fixed problems', deriveProblems('r', series[2].derive, (x) => series.find((s) => s.id === x)?.frequency, 'quarterly').length === 0, 'the annual denominator is not on the quarterly schedule and that is allowed');
});
plainCase('derive: the period helpers', () => {
  return check('isPeriodEnd', isPeriodEnd('2024-09-30', 'quarterly') && isPeriodEnd('2024-02-29', 'monthly') && !isPeriodEnd('2024-09-29', 'quarterly') && !isPeriodEnd('2024-10-31', 'quarterly') && !isPeriodEnd('2024-02-30', 'monthly') && !isPeriodEnd('2024-09-30', 'annual'), 'period ends')
    && check('periodsBetween', periodsBetween('2024-06-30', '2029-06-30', 'quarterly') === 20 && periodsBetween('2024-06-30', '2024-06-30', 'quarterly') === 0 && periodsBetween('2029-06-30', '2024-06-30', 'quarterly') === null && periodsBetween('2024-01-31', '2024-04-30', 'monthly') === 3, 'periods')
    && check('periodLabel', periodLabel('2026-06-30', 'quarterly') === '2026-Q2' && periodLabel('2026-02-28', 'monthly') === '2026-02', 'labels')
    && check('isRealIsoDate', isRealIsoDate('2024-02-29') && !isRealIsoDate('2023-02-29') && !isRealIsoDate('2024-2-9') && !isRealIsoDate(20240229), 'dates')
    && check('shiftPeriods forward', shiftPeriods('2024-06-30', -1, 'quarterly') === '2024-09-30' && shiftPeriods('2024-12-31', -1, 'quarterly') === '2025-03-31', 'forward');
});

rmSync(base, { recursive: true, force: true });

console.log(`\n${passed} passed, ${failed} failed (${passed + failed} cases)`);
if (failed > 0) {
  console.log('\nDetails of the failures:');
  for (const f of failures) console.log(`- ${f}`);
  process.exitCode = 1;
}
