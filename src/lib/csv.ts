// A small CSV reader. The files in this project never contain quoted fields or
// commas inside values, so there is no quote handling. If a quote character
// turns up, stop loudly rather than read the file wrongly.
export function parseCsv(text: string, label = 'csv'): Record<string, string>[] {
  if (text.includes('"')) {
    throw new Error(`${label}: contains a quote character. This reader does not support quoted fields.`);
  }
  const lines = text.replace(/\r\n?/g, '\n').split('\n').filter((l) => l.trim() !== '');
  if (lines.length === 0) throw new Error(`${label}: file is empty.`);
  const header = lines[0].split(',').map((h) => h.trim());
  return lines.slice(1).map((line, i) => {
    const cells = line.split(',');
    if (cells.length !== header.length) {
      throw new Error(`${label}: line ${i + 2} has ${cells.length} fields, expected ${header.length}.`);
    }
    const row: Record<string, string> = {};
    header.forEach((h, j) => (row[h] = cells[j].trim()));
    return row;
  });
}
