// Number and date formatting, driven by the unit named in data.csv.
// Used both when the page is built and in the chart script in the browser.

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function unknownUnit(unit: string): never {
  throw new Error(`Unknown unit "${unit}". Add it to src/lib/format.ts.`);
}

// An index number as the ABS gives it: one or two decimal places, no % sign (103.3, 7.07, 100.25).
// The data holds at most two decimals, so the second is shown only when it is not zero.
function indexText(v: number): string {
  const s = v.toFixed(2);
  return s.endsWith('0') ? s.slice(0, -1) : s;
}

// A whole number with thousands separators (450,607).
function countText(v: number): string {
  return Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Read-outs, tiles and chart end labels.
export function formatValue(unit: string, v: number): string {
  if (unit === 'aud_million') {
    const b = v / 1000;
    return (b < 0 ? '−$' : '$') + Math.abs(b).toFixed(1) + 'b';
  }
  if (unit === 'pct_gdp') return v.toFixed(1) + '%';
  if (unit === 'pct') return v.toFixed(1) + '%';
  if (unit === 'index') return indexText(v);
  if (unit === 'count') return countText(v);
  if (unit === 'rate') return v.toFixed(1);
  return unknownUnit(unit);
}

// Labels on the y axis.
export function formatAxis(unit: string, v: number): string {
  if (unit === 'aud_million') return (v < 0 ? '−$' : '$') + +Math.abs(v / 1000).toFixed(3) + 'b';
  if (unit === 'pct_gdp') return v + '%';
  if (unit === 'pct') return v + '%';
  if (unit === 'index') return String(+v.toFixed(2));
  if (unit === 'count') return Math.abs(v) >= 1000 ? +(v / 1000).toFixed(1) + 'k' : String(v);
  if (unit === 'rate') return String(+v.toFixed(1));
  return unknownUnit(unit);
}

// Cells in the full table.
export function formatTable(unit: string, v: number): string {
  if (unit === 'aud_million') return Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  if (unit === 'pct_gdp') return v.toFixed(1);
  if (unit === 'pct') return v.toFixed(1);
  if (unit === 'index') return indexText(v);
  if (unit === 'count') return countText(v);
  if (unit === 'rate') return v.toFixed(1);
  return unknownUnit(unit);
}

// "YYYY-MM-DD" -> "30 June YYYY" style (day, month name, year)
export function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Not a date: ${iso}`);
  return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
}

// "YYYY-MM-DD" -> "June 2026" style (month name and year)
export function formatMonthYear(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Not a date: ${iso}`);
  return `${MONTHS[+m[2] - 1]} ${m[1]}`;
}

// "YYYY-MM-DD" at the end of a quarter -> "September quarter 2026"
export function formatQuarterYear(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Not a date: ${iso}`);
  if (![3, 6, 9, 12].includes(+m[2])) throw new Error(`Not the end of a quarter: ${iso}`);
  return `${MONTHS[+m[2] - 1]} quarter ${m[1]}`;
}

// "YYYY-MM-DD" -> the year plus the fraction of the year gone, for placing marks on the x axis.
export function decimalYear(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Not a date: ${iso}`);
  const y = +m[1];
  const start = Date.UTC(y, 0, 1);
  const end = Date.UTC(y + 1, 0, 1);
  return y + (Date.UTC(y, +m[2] - 1, +m[3]) - start) / (end - start);
}
