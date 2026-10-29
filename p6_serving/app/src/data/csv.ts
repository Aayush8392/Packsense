/** Reads comma-separated text (RFC 4180: quoted fields, doubled quotes, line breaks inside quotes) into rows keyed by the header line. */
export function parseCsv(text: string): Record<string, string>[] {
  const records: string[][] = [];
  let field = '';
  let record: string[] = [];
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ',') {
      record.push(field);
      field = '';
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i += 1;
      record.push(field);
      field = '';
      records.push(record);
      record = [];
    } else {
      field += char;
    }
  }
  if (field !== '' || record.length > 0) {
    record.push(field);
    records.push(record);
  }

  const [header, ...body] = records.filter((r) => !(r.length === 1 && r[0] === ''));
  if (!header) return [];
  return body.map((row) => Object.fromEntries(header.map((name, i) => [name, row[i] ?? ''])));
}
