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
const dataPath = () => p('metrics', SLUG, 'data.csv');
const readText = (f) => readFileSync(f, 'utf8');
const sha = (f) => createHash('sha256').update(readFileSync(f)).digest('hex');

// Edit data.csv line by line. `fn(line)` returns the new line, an array of lines, or null to delete.
function editRows(match, fn) {
  const lines = readText(dataPath()).split('\n');
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
  writeFileSync(dataPath(), out.join('\n'));
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

plainCase('every problem is printed, not just the first', () => {
  editRows(row('1990-06-30', 'gross_debt'), (l) => setValue(l, 'abc'));
  editRows(row('2000-06-30', 'gross_debt_pct_gdp'), (l) => setValue(l, '150'));
  const r = run();
  return check('all problems', /the value "abc"/.test(r.out) && /outside the plausible range 0 to 100/.test(r.out), r.out);
});

rmSync(base, { recursive: true, force: true });

console.log(`\n${passed} passed, ${failed} failed (${passed + failed} cases)`);
if (failed > 0) {
  console.log('\nDetails of the failures:');
  for (const f of failures) console.log(`- ${f}`);
  process.exitCode = 1;
}
