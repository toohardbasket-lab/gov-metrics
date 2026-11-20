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

rmSync(base, { recursive: true, force: true });

console.log(`\n${passed} passed, ${failed} failed (${passed + failed} cases)`);
if (failed > 0) {
  console.log('\nDetails of the failures:');
  for (const f of failures) console.log(`- ${f}`);
  process.exitCode = 1;
}
