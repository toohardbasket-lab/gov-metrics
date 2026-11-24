// Derived series: figures worked out from a stored series when the site is built or checked.
// Used by scripts/validate.mjs (the checker) and src/lib/metrics.ts (the page), so both work out
// exactly the same figures. Plain JavaScript with no packages.
//
// metric.yml declares a derived series on its `series` list instead of storing it in data.csv:
//
//   - id: rents_quarterly
//     derive: {type: year_ended_change, from: rents_index_quarterly, lag: 4}
//
// year_ended_change: (value this period / value `lag` periods earlier - 1) x 100, rounded half up to
// one decimal place (a tie goes away from zero, as the scrapers' ROUND_HALF_UP does). The sums use
// whole numbers (BigInt) on the figures as written in data.csv, so no floating point can tip a
// rounding. A period with no figure `lag` periods earlier (the start of the series, or a gap) has no
// derived figure: it is left out, never filled in or worked out from a different period.

export const DERIVE_TYPES = ['year_ended_change'];
// The frequencies a derived series can step through: months per period.
export const DERIVE_FREQUENCIES = { monthly: 1, quarterly: 3 };

// "103.30" -> { n: 10330n, scale: 2 }. Returns null for anything that is not a plain decimal number.
export function parseDecimal(text) {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(text).trim());
  if (!m) return null;
  const frac = m[3] ?? '';
  const n = BigInt(m[2] + frac) * (m[1] === '-' ? -1n : 1n);
  return { n, scale: frac.length };
}

// (a / b - 1) x 100 for two decimal numbers written as text, as text with one decimal place.
// Returns null if either is not a number or b is not above zero.
export function yearEndedChangeText(aText, bText) {
  const a = parseDecimal(aText);
  const b = parseDecimal(bText);
  if (!a || !b) return null;
  const scale = Math.max(a.scale, b.scale);
  const A = a.n * 10n ** BigInt(scale - a.scale);
  const B = b.n * 10n ** BigInt(scale - b.scale);
  if (B <= 0n) return null;
  // change in tenths of a point = (A - B) / B x 1000, rounded half away from zero
  const num = (A - B) * 1000n;
  const abs = num < 0n ? -num : num;
  const tenths = (2n * abs + B) / (2n * B);
  const sign = num < 0n && tenths !== 0n ? '-' : '';
  return `${sign}${tenths / 10n}.${tenths % 10n}`;
}

// The date `periods` periods before `iso` (a last day of a month), also a last day of a month.
export function shiftPeriods(iso, periods, frequency) {
  const step = DERIVE_FREQUENCIES[frequency];
  if (!step) return null;
  const [y, m] = iso.split('-').map(Number);
  const total = y * 12 + (m - 1) - periods * step;
  const ny = Math.floor(total / 12);
  const nm = (total % 12) + 1;
  const last = new Date(Date.UTC(ny, nm, 0)).getUTCDate();
  return `${String(ny).padStart(4, '0')}-${String(nm).padStart(2, '0')}-${String(last).padStart(2, '0')}`;
}

// rows: [{ date, period, valueText }] of the source series (one jurisdiction), any order.
// Returns [{ date, period, valueText, value, current, earlier }] oldest first, only for dates that
// have a figure `lag` periods earlier.
export function deriveYearEndedChange(rows, lag, frequency) {
  const byDate = new Map(rows.map((r) => [r.date, r]));
  const out = [];
  for (const r of [...rows].sort((x, y) => (x.date < y.date ? -1 : x.date > y.date ? 1 : 0))) {
    const prevDate = shiftPeriods(r.date, lag, frequency);
    const prev = prevDate === null ? undefined : byDate.get(prevDate);
    if (!prev) continue;
    const text = yearEndedChangeText(r.valueText, prev.valueText);
    if (text === null) continue;
    out.push({ date: r.date, period: r.period, valueText: text, value: Number(text), current: r.valueText, earlier: prev.valueText, earlierDate: prevDate });
  }
  return out;
}

// Problems with a series' `derive` setting, as a list of plain-words messages (empty if fine).
// `sourceFrequency` is the frequency declared on the series it is taken from.
export function deriveProblems(id, derive, sourceFrequency, ownFrequency) {
  const bad = [];
  if (!derive || typeof derive !== 'object' || Array.isArray(derive)) return [`series "${id}" has a "derive" that is not a set of fields. Use for example "derive: {type: year_ended_change, from: <series id>, lag: 4}".`];
  for (const k of Object.keys(derive)) {
    if (!['type', 'from', 'lag'].includes(k)) bad.push(`series "${id}" has a "derive" field "${k}" that the checker does not know. Known: type, from, lag.`);
  }
  if (!DERIVE_TYPES.includes(derive.type)) bad.push(`series "${id}" has derive type "${derive.type}", which the site does not know. Known: ${DERIVE_TYPES.join(', ')}.`);
  if (typeof derive.from !== 'string' || derive.from === '') bad.push(`series "${id}" has a "derive" with no "from" (the stored series it is worked out from).`);
  if (!Number.isInteger(derive.lag) || derive.lag < 1) bad.push(`series "${id}" has a "derive" "lag" that is not a whole number of periods above zero.`);
  if (sourceFrequency !== undefined && !DERIVE_FREQUENCIES[sourceFrequency]) bad.push(`series "${id}" is worked out from a ${sourceFrequency} series; derive supports ${Object.keys(DERIVE_FREQUENCIES).join(' and ')}.`);
  if (sourceFrequency !== undefined && ownFrequency !== undefined && sourceFrequency !== ownFrequency) bad.push(`series "${id}" says it is ${ownFrequency} but the series it is worked out from is ${sourceFrequency}.`);
  return bad;
}
