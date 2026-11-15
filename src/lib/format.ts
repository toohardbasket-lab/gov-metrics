// Number and date formatting, driven by the unit named in data.csv.
// Used both when the page is built and in the chart script in the browser.

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function unknownUnit(unit: string): never {
  throw new Error(`Unknown unit "${unit}". Add it to src/lib/format.ts.`);
}

// Read-outs, tiles and chart end labels.
export function formatValue(unit: string, v: number): string {
  if (unit === 'aud_million') {
    const b = v / 1000;
    return (b < 0 ? '−$' : '$') + Math.abs(b).toFixed(1) + 'b';
  }
  if (unit === 'pct_gdp') return v.toFixed(1) + '%';
  return unknownUnit(unit);
}

// Labels on the y axis.
export function formatAxis(unit: string, v: number): string {
  if (unit === 'aud_million') return (v < 0 ? '−$' : '$') + +Math.abs(v / 1000).toFixed(3) + 'b';
  if (unit === 'pct_gdp') return v + '%';
  return unknownUnit(unit);
}

// Cells in the full table.
export function formatTable(unit: string, v: number): string {
  if (unit === 'aud_million') return Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  if (unit === 'pct_gdp') return v.toFixed(1);
  return unknownUnit(unit);
}

// "YYYY-MM-DD" -> "30 June YYYY" style (day, month name, year)
export function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Not a date: ${iso}`);
  return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
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
