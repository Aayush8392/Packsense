/** The sample file with the eight "exactly this many" columns added: every brand's products sit on the two neighbouring counts that give its points. */
export function withSpread(csv: string): string {
  const lines = csv.trim().split('\n');
  const header = lines[0].split(',');
  const at = (name: string) => header.indexOf(name);
  const out = [[...header, ...Array.from({ length: 8 }, (_, i) => `n_filled_${i}`)].join(',')];
  for (const line of lines.slice(1)) {
    const cells = line.split(',');
    const products = Number(cells[at('n_products')]);
    const points = Number(cells[at('coverage_points')]);
    const low = Math.floor(points / products);
    const high = points - low * products; // this many products sit one count higher
    const spread = Array.from({ length: 8 }, (_, i) => (i === low ? products - high : 0) + (i === low + 1 ? high : 0));
    out.push([...cells, ...spread].join(','));
  }
  return `${out.join('\n')}\n`;
}
