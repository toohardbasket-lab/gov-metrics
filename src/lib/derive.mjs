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
//
// sum: the total of several stored or derived series for the same jurisdiction and date.
//   derive: {type: sum, from: [public_housing, somih, community_housing, indigenous_community_housing]}
// ratio: numerator / denominator x factor, rounded half up to `decimals` places, shown in `unit`.
//   derive: {type: ratio, numerator: total_social_housing, denominator: population, factor: 1000, decimals: 1, unit: rate}
//
// cumulative_sum: a running total of one series, per jurisdiction, from a start date.
//   derive: {type: cumulative_sum, from: completions, start: 2024-09-30}
//   The total at a date is the sum of the figures from `start` up to and including that date. There is no
//   figure before `start`. If a date from `start` on has no figure (a gap), or a code that makes it unknown
//   (na, np), every later total is blank: the total is never worked out across a gap.
// straight_line: the even pace from one point to another, one figure at the end of each period (month or
//   quarter, the series' own `frequency`) after the start date up to the end date. It reads no stored series.
//   derive: {type: straight_line, start: {date: 2024-06-30, value: 0}, end: {date: 2029-06-30, value: 1200000}, jurisdiction: Australia, unit: count, decimals: 0}
//   The value k periods after the start is start + (end - start) x k / n, where n is the number of periods from
//   the start date to the end date, rounded half away from zero to `decimals` places (default 0).
// A ratio may divide by the figure at one fixed date instead of the figure at each date:
//   derive: {type: ratio, numerator: accord_completed, denominator: population_june_2024, denominator_date: 2024-06-30, factor: 1000, decimals: 1, unit: rate}
//
// Codes. A stored value may be a code the source uses instead of a number (see VALUE_CODES). In a sum,
// `..` (not applicable) and `-` (nil, or rounded to zero) count as zero; `na` (not available) and `np`
// (not published) make that total blank: the total is unknown and is never guessed. A date with no row
// in one of the parts is blank as well. In a ratio any code, a missing figure, or a denominator that is
// not above zero makes the ratio blank. A blank figure is left out (it has no row), and the reason is
// returned in `blanks` so it can be reported. Derived series may be worked out from other derived series.

export const DERIVE_TYPES = ['year_ended_change', 'sum', 'ratio', 'cumulative_sum', 'straight_line'];
// What a stored value may be instead of a number. Used by the checker, the page and (as text) the scrapers.
export const VALUE_CODES = ['..', 'na', 'np', '-'];
export const ZERO_CODES = ['..', '-'];
export const UNKNOWN_CODES = ['na', 'np'];
export const isValueCode = (text) => VALUE_CODES.includes(String(text).trim());
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

// The stored or derived series a derived series is worked out from, in the order its settings list them.
export function deriveInputs(derive) {
  if (!derive || typeof derive !== 'object') return [];
  if (derive.type === 'year_ended_change') return typeof derive.from === 'string' ? [derive.from] : [];
  if (derive.type === 'sum') return Array.isArray(derive.from) ? derive.from.filter((x) => typeof x === 'string') : [];
  if (derive.type === 'ratio') return [derive.numerator, derive.denominator].filter((x) => typeof x === 'string');
  if (derive.type === 'cumulative_sum') return typeof derive.from === 'string' ? [derive.from] : [];
  return []; // straight_line reads no series
}

// The inputs whose schedule (frequency) must match the derived series' own. A ratio with a fixed denominator date
// divides by a figure at one date, so only its numerator is on the schedule.
function scheduledInputs(derive) {
  if (derive?.type === 'ratio' && derive.denominator_date !== undefined) return typeof derive.numerator === 'string' ? [derive.numerator] : [];
  return deriveInputs(derive);
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export function isRealIsoDate(text) {
  if (typeof text !== 'string' || !ISO_DATE.test(text)) return false;
  const [y, m, d] = text.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

// Is this date the last day of a period of the given frequency (month, or quarter)?
export function isPeriodEnd(iso, frequency) {
  const step = DERIVE_FREQUENCIES[frequency];
  if (!step || !isRealIsoDate(iso)) return false;
  const [y, m, d] = iso.split('-').map(Number);
  return m % step === 0 && d === new Date(Date.UTC(y, m, 0)).getUTCDate();
}

// The number of periods from `a` to `b` (both period ends, b not before a), or null.
export function periodsBetween(a, b, frequency) {
  if (!isPeriodEnd(a, frequency) || !isPeriodEnd(b, frequency) || b < a) return null;
  let n = 0;
  let d = a;
  while (d < b && n < 100000) { d = shiftPeriods(d, -1, frequency); n++; }
  return d === b ? n : null;
}

// The label of the period that ends on `iso`: 2026-Q2 for a quarter, 2026-06 for a month.
export function periodLabel(iso, frequency) {
  const [y, m] = iso.split('-');
  return frequency === 'quarterly' ? `${y}-Q${Number(m) / 3}` : `${y}-${m}`;
}

// Problems with a series' `derive` setting, as a list of plain-words messages (empty if fine).
// `freqOf(id)` gives the frequency declared on a series (undefined if it is not declared);
// `ownFrequency` is the one declared on the derived series itself.
export function deriveProblems(id, derive, freqOf, ownFrequency) {
  const bad = [];
  if (!derive || typeof derive !== 'object' || Array.isArray(derive)) return [`series "${id}" has a "derive" that is not a set of fields. Use for example "derive: {type: year_ended_change, from: <series id>, lag: 4}".`];
  const KNOWN = { year_ended_change: ['type', 'from', 'lag'], sum: ['type', 'from'], ratio: ['type', 'numerator', 'denominator', 'denominator_date', 'factor', 'decimals', 'unit'], cumulative_sum: ['type', 'from', 'start'], straight_line: ['type', 'start', 'end', 'jurisdiction', 'unit', 'decimals'] };
  if (!DERIVE_TYPES.includes(derive.type)) {
    bad.push(`series "${id}" has derive type "${derive.type}", which the site does not know. Known: ${DERIVE_TYPES.join(', ')}.`);
    return bad;
  }
  for (const k of Object.keys(derive)) {
    if (!KNOWN[derive.type].includes(k)) bad.push(`series "${id}" has a "derive" field "${k}" that the checker does not know for type ${derive.type}. Known: ${KNOWN[derive.type].join(', ')}.`);
  }
  if (derive.type === 'year_ended_change') {
    if (typeof derive.from !== 'string' || derive.from === '') bad.push(`series "${id}" has a "derive" with no "from" (the stored series it is worked out from).`);
    if (!Number.isInteger(derive.lag) || derive.lag < 1) bad.push(`series "${id}" has a "derive" "lag" that is not a whole number of periods above zero.`);
    const f = typeof derive.from === 'string' ? freqOf(derive.from) : undefined;
    if (f !== undefined && !DERIVE_FREQUENCIES[f]) bad.push(`series "${id}" is worked out from a ${f} series; year_ended_change supports ${Object.keys(DERIVE_FREQUENCIES).join(' and ')}.`);
  } else if (derive.type === 'cumulative_sum') {
    if (typeof derive.from !== 'string' || derive.from === '') bad.push(`series "${id}" has a "derive" of type cumulative_sum with no "from" (the series it adds up).`);
    if (!isRealIsoDate(derive.start)) bad.push(`series "${id}" has a "derive" "start" that is not a real date written YYYY-MM-DD (the first date of the running total).`);
    const f = typeof derive.from === 'string' ? freqOf(derive.from) : undefined;
    if (f !== undefined && !DERIVE_FREQUENCIES[f]) bad.push(`series "${id}" adds up a ${f} series; cumulative_sum supports ${Object.keys(DERIVE_FREQUENCIES).join(' and ')}.`);
    else if (f !== undefined && isRealIsoDate(derive.start) && !isPeriodEnd(derive.start, f)) bad.push(`series "${id}" starts its running total on ${derive.start}, which is not the last day of a ${f === 'monthly' ? 'month' : 'quarter'}.`);
  } else if (derive.type === 'straight_line') {
    const f = ownFrequency;
    if (!DERIVE_FREQUENCIES[f]) bad.push(`series "${id}" is a straight_line and needs "frequency" to be ${Object.keys(DERIVE_FREQUENCIES).join(' or ')} (the periods it has a figure for).`);
    const point = (k) => {
      const p = derive[k];
      if (!p || typeof p !== 'object' || Array.isArray(p) || Object.keys(p).some((x) => x !== 'date' && x !== 'value')) { bad.push(`series "${id}" has a "derive" "${k}" that is not {date: YYYY-MM-DD, value: <number>}.`); return null; }
      let ok = true;
      if (!isRealIsoDate(p.date)) { bad.push(`series "${id}" has a "derive" "${k}" with a "date" that is not a real date written YYYY-MM-DD.`); ok = false; }
      else if (DERIVE_FREQUENCIES[f] && !isPeriodEnd(p.date, f)) { bad.push(`series "${id}" has a "derive" "${k}" date ${p.date}, which is not the last day of a ${f === 'monthly' ? 'month' : 'quarter'}.`); ok = false; }
      if (typeof p.value !== 'number' || !Number.isFinite(p.value) || parseDecimal(String(p.value)) === null) { bad.push(`series "${id}" has a "derive" "${k}" with a "value" that is not a plain number.`); ok = false; }
      return ok ? p : null;
    };
    const a = point('start');
    const b = point('end');
    if (a && b && DERIVE_FREQUENCIES[f] && periodsBetween(a.date, b.date, f) === null) bad.push(`series "${id}" has a "derive" whose "end" date is not after its "start" date.`);
    else if (a && b && periodsBetween(a.date, b.date, f) === 0) bad.push(`series "${id}" has a "derive" whose "end" date is the same as its "start" date.`);
    if (typeof derive.jurisdiction !== 'string' || derive.jurisdiction.trim() === '') bad.push(`series "${id}" has a "derive" of type straight_line with no "jurisdiction" (the jurisdiction its figures are for).`);
    if (typeof derive.unit !== 'string' || derive.unit === '') bad.push(`series "${id}" has a "derive" of type straight_line with no "unit" (the unit its figures are shown in).`);
    if (derive.decimals !== undefined && (!Number.isInteger(derive.decimals) || derive.decimals < 0 || derive.decimals > 6)) bad.push(`series "${id}" has a "derive" "decimals" that is not a whole number from 0 to 6.`);
  } else if (derive.type === 'sum') {
    if (!Array.isArray(derive.from) || derive.from.length < 2 || derive.from.some((x) => typeof x !== 'string' || x === '')) bad.push(`series "${id}" has a "derive" of type sum whose "from" is not a list of at least two series ids.`);
    else if (new Set(derive.from).size !== derive.from.length) bad.push(`series "${id}" has a "derive" of type sum that lists a series twice.`);
  } else {
    for (const k of ['numerator', 'denominator']) {
      if (typeof derive[k] !== 'string' || derive[k] === '') bad.push(`series "${id}" has a "derive" of type ratio with no "${k}" (a series id).`);
    }
    if (derive.numerator !== undefined && derive.numerator === derive.denominator) bad.push(`series "${id}" divides a series by itself.`);
    if (!Number.isInteger(derive.factor) || derive.factor < 1) bad.push(`series "${id}" has a "derive" "factor" that is not a whole number above zero.`);
    if (!Number.isInteger(derive.decimals) || derive.decimals < 0 || derive.decimals > 6) bad.push(`series "${id}" has a "derive" "decimals" that is not a whole number from 0 to 6.`);
    if (typeof derive.unit !== 'string' || derive.unit === '') bad.push(`series "${id}" has a "derive" of type ratio with no "unit" (the unit its figures are shown in).`);
    if (derive.denominator_date !== undefined && !isRealIsoDate(derive.denominator_date)) bad.push(`series "${id}" has a "derive" "denominator_date" that is not a real date written YYYY-MM-DD.`);
  }
  if (derive.type === 'sum' || derive.type === 'ratio' || derive.type === 'cumulative_sum') {
    // these take the same period from each input, so every input must be on the same schedule
    // (a ratio with a fixed denominator date has only its numerator on the schedule)
    for (const src of scheduledInputs(derive)) {
      const f = freqOf(src);
      if (f !== undefined && ownFrequency !== undefined && f !== ownFrequency) bad.push(`series "${id}" says it is ${ownFrequency} but "${src}", which it is worked out from, is ${f}.`);
    }
  } else if (derive.type === 'straight_line') {
    // nothing to compare: it reads no series
  } else {
    const f = typeof derive.from === 'string' ? freqOf(derive.from) : undefined;
    if (f !== undefined && ownFrequency !== undefined && f !== ownFrequency) bad.push(`series "${id}" says it is ${ownFrequency} but the series it is worked out from is ${f}.`);
  }
  return bad;
}

// ---------------------------------------------------------------- exact arithmetic on decimal text

// BigInt division rounded half away from zero (den above zero).
function divRound(num, den) {
  const abs = num < 0n ? -num : num;
  const q = (2n * abs + den) / (2n * den);
  return num < 0n ? -q : q;
}

// A scaled integer back to text with `scale` decimal places ("-" only if the figure is not zero).
function scaledText(n, scale) {
  const neg = n < 0n;
  const digits = (neg ? -n : n).toString().padStart(scale + 1, '0');
  const body = scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
  return neg && n !== 0n ? `-${body}` : body;
}

// The total of several figures written as text (numbers or codes). Returns {text} or {blank: reason}.
// `..` and `-` count as zero; `na` and `np` make the total unknown (blank); anything else is refused (blank).
export function sumText(parts) {
  let scale = 0;
  const nums = [];
  let unknown = null;
  for (const t of parts) {
    const text = String(t).trim();
    if (ZERO_CODES.includes(text)) continue;
    if (UNKNOWN_CODES.includes(text)) { unknown ??= text; continue; }
    const d = parseDecimal(text);
    if (!d) return { blank: `"${text}" is not a number or a known code` };
    nums.push(d);
    scale = Math.max(scale, d.scale);
  }
  if (unknown !== null) return { blank: `a part is ${unknown}, so the total is unknown` };
  const total = nums.reduce((a, d) => a + d.n * 10n ** BigInt(scale - d.scale), 0n);
  return { text: scaledText(total, scale) };
}

// numerator / denominator x factor, rounded half away from zero to `decimals` places, as text.
// Returns {text} or {blank: reason}. A code, or a denominator that is not above zero, is blank.
export function ratioText(numText, denText, factor, decimals) {
  const a = parseDecimal(numText);
  const b = parseDecimal(denText);
  if (!a) return { blank: isValueCode(numText) ? `the numerator is ${String(numText).trim()}` : `"${numText}" is not a number` };
  if (!b) return { blank: isValueCode(denText) ? `the denominator is ${String(denText).trim()}` : `"${denText}" is not a number` };
  if (b.n <= 0n) return { blank: 'the denominator is not above zero' };
  // (a.n / 10^sa) / (b.n / 10^sb) x factor x 10^decimals = a.n x 10^sb x factor x 10^decimals / (b.n x 10^sa)
  const num = a.n * 10n ** BigInt(b.scale) * BigInt(factor) * 10n ** BigInt(decimals);
  const den = b.n * 10n ** BigInt(a.scale);
  return { text: scaledText(divRound(num, den), decimals) };
}

// ---------------------------------------------------------------- working out every derived series

// seriesList: the "series" list of metric.yml. stored: Map "seriesId|jurisdiction" -> [{date, period,
// valueText, unit}] (any order) for every stored series. Returns
//   groups: Map "seriesId|jurisdiction" -> [{date, period, valueText, value, unit, derivedFrom}] oldest first,
//           for every derived series (a derived series may be worked out from another derived series);
//   blanks: [{series, jurisdiction, date, reason}] dates where a derived series has no figure because an
//           input was unknown, missing or a code (year_ended_change leaves its early periods out without a note);
//   problems: plain-words messages (a series worked out from an unknown series, a loop, mixed units).
export function computeDerived(seriesList, stored) {
  const byId = new Map(seriesList.filter((s) => s && typeof s.id === 'string').map((s) => [s.id, s]));
  const groups = new Map();
  const blanks = [];
  const problems = [];
  const state = new Map(); // id -> 'working' | 'done' | 'failed'
  const byDate = (a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
  const jurisdictionsOf = (id) => {
    const out = new Set();
    for (const k of [...stored.keys(), ...groups.keys()]) if (k.startsWith(`${id}|`)) out.add(k.slice(id.length + 1));
    return out;
  };
  const rowsOf = (id, j) => groups.get(`${id}|${j}`) ?? stored.get(`${id}|${j}`);

  function work(id) {
    const s = byId.get(id);
    if (state.get(id) === 'done' || state.get(id) === 'failed') return state.get(id) === 'done';
    if (state.get(id) === 'working') { problems.push(`series "${id}" is worked out from itself (through other derived series).`); state.set(id, 'failed'); return false; }
    state.set(id, 'working');
    const inputs = deriveInputs(s.derive);
    let ok = true;
    for (const src of inputs) {
      const t = byId.get(src);
      if (!t) { problems.push(`series "${id}" is worked out from "${src}", which is not in the "series" list.`); ok = false; }
      else if (t.derive !== undefined) { if (!work(src)) ok = false; }
    }
    if (!ok || (inputs.length === 0 && s.derive?.type !== 'straight_line') || !DERIVE_TYPES.includes(s.derive?.type)) { state.set(id, 'failed'); return false; }
    const d = s.derive;
    const js = new Set();
    if (d.type === 'straight_line') js.add(d.jurisdiction);
    for (const src of inputs) for (const j of jurisdictionsOf(src)) js.add(j);
    for (const j of [...js].sort()) {
      const rows = [];
      if (d.type === 'year_ended_change') {
        const src = rowsOf(d.from, j) ?? [];
        const freq = byId.get(d.from)?.frequency;
        for (const r of deriveYearEndedChange(src.map((x) => ({ date: x.date, period: x.period, valueText: x.valueText })), d.lag, freq)) {
          rows.push({ date: r.date, period: r.period, valueText: r.valueText, value: r.value, unit: 'pct', derivedFrom: `${d.from} ${r.current} on ${r.date} and ${r.earlier} on ${r.earlierDate}` });
        }
      } else if (d.type === 'cumulative_sum') {
        // a running total from d.start; a date with no figure, or an unknown code, blanks that date and every later one
        const freq = byId.get(d.from)?.frequency;
        if (!DERIVE_FREQUENCIES[freq]) { problems.push(`series "${id}" adds up "${d.from}", which is ${freq ?? 'of no stated'} frequency; cumulative_sum supports ${Object.keys(DERIVE_FREQUENCIES).join(' and ')}.`); state.set(id, 'failed'); return false; }
        const src = rowsOf(d.from, j) ?? [];
        const byD = new Map(src.map((x) => [x.date, x]));
        const lastDate = src.map((x) => x.date).sort().at(-1);
        const unit = src.find((x) => x.unit !== undefined)?.unit;
        let running = null;
        let brokenAt = null;
        for (let date = d.start; lastDate !== undefined && date <= lastDate; date = shiftPeriods(date, -1, freq)) {
          if (brokenAt !== null) { if (byD.has(date)) blanks.push({ series: id, jurisdiction: j, date, reason: `the running total of ${d.from} is blank after ${brokenAt}, which had no usable figure` }); continue; }
          const r = byD.get(date);
          if (!r) { brokenAt = date; blanks.push({ series: id, jurisdiction: j, date, reason: `${d.from} has no figure for ${date}, so the running total from ${d.start} stops here` }); continue; }
          const t = sumText(running === null ? [r.valueText] : [running, r.valueText]);
          if (t.blank !== undefined) { brokenAt = date; blanks.push({ series: id, jurisdiction: j, date, reason: `${t.blank} (${d.from} ${r.valueText} on ${date})` }); continue; }
          running = t.text;
          rows.push({ date, period: r.period, valueText: running, value: Number(running), unit, derivedFrom: `the running total of ${d.from} from ${d.start} to ${date}` });
        }
      } else if (d.type === 'straight_line') {
        const freq = s.frequency;
        const n = DERIVE_FREQUENCIES[freq] ? periodsBetween(d.start.date, d.end.date, freq) : null;
        if (!n) { problems.push(`series "${id}" is a straight_line whose start and end dates are not period ends of its ${freq} frequency, or whose end is not after its start.`); state.set(id, 'failed'); return false; }
        const decimals = d.decimals ?? 0;
        const a = parseDecimal(String(d.start.value));
        const b = parseDecimal(String(d.end.value));
        if (!a || !b) { problems.push(`series "${id}" is a straight_line whose start or end value is not a plain number.`); state.set(id, 'failed'); return false; }
        const scale = Math.max(a.scale, b.scale);
        const A = a.n * 10n ** BigInt(scale - a.scale);
        const B = b.n * 10n ** BigInt(scale - b.scale);
        for (let k = 1; k <= n; k++) {
          const date = shiftPeriods(d.start.date, -k, freq);
          // start + (end - start) x k / n, exactly, then rounded half away from zero to `decimals` places
          const num = (A * BigInt(n) + (B - A) * BigInt(k)) * 10n ** BigInt(decimals);
          const text = scaledText(divRound(num, BigInt(n) * 10n ** BigInt(scale)), decimals);
          rows.push({ date, period: periodLabel(date, freq), valueText: text, value: Number(text), unit: d.unit, derivedFrom: `a straight line from ${d.start.value} on ${d.start.date} to ${d.end.value} on ${d.end.date}, ${k} of ${n} periods` });
        }
      } else {
        const maps = inputs.map((src) => new Map((rowsOf(src, j) ?? []).map((x) => [x.date, x])));
        const fixed = d.type === 'ratio' && d.denominator_date !== undefined; // divide by the denominator's figure at one date
        const dates = fixed ? [...maps[0].keys()].sort() : [...new Set(maps.flatMap((m) => [...m.keys()]))].sort();
        let unit;
        if (d.type === 'sum') {
          const units = new Set(maps.flatMap((m) => [...m.values()].map((x) => x.unit)).filter((u) => u !== undefined));
          if (units.size > 1) { problems.push(`series "${id}" adds series that are in different units (${[...units].join(', ')}).`); state.set(id, 'failed'); return false; }
          unit = [...units][0];
        } else unit = d.unit;
        for (const date of dates) {
          const parts = maps.map((m, i) => m.get(fixed && i === 1 ? d.denominator_date : date));
          const missing = parts.findIndex((p) => p === undefined);
          if (missing >= 0) { blanks.push({ series: id, jurisdiction: j, date, reason: `${inputs[missing]} has no figure for ${fixed && missing === 1 ? d.denominator_date : date}` }); continue; }
          const r = d.type === 'sum' ? sumText(parts.map((p) => p.valueText)) : ratioText(parts[0].valueText, parts[1].valueText, d.factor, d.decimals);
          const period = parts[0].period;
          if (r.blank !== undefined) { blanks.push({ series: id, jurisdiction: j, date, reason: `${r.blank} (${inputs.map((n, i) => `${n} ${parts[i].valueText}`).join(', ')})` }); continue; }
          rows.push({ date, period, valueText: r.text, value: Number(r.text), unit, derivedFrom: inputs.map((n, i) => `${n} ${parts[i].valueText}`).join(d.type === 'sum' ? ' + ' : ' and ') + (fixed ? ` (${d.denominator} on ${d.denominator_date})` : '') + ` on ${date}` });
        }
      }
      if (rows.length > 0) groups.set(`${id}|${j}`, rows.sort(byDate));
    }
    state.set(id, 'done');
    return true;
  }
  for (const s of byId.values()) if (s.derive !== undefined) work(s.id);
  return { groups, blanks, problems };
}
