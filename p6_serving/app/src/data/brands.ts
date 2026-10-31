import type { BrandRow } from './siteData';
import type { Scope } from './series';

/** The seven things checked on every product, in the order the page text lists them. The keys are the ones in the scorecard parser. */
export const ITEMS: { key: string; label: string }[] = [
  { key: 'nutrition', label: 'Nutrition' },
  { key: 'nutriscore', label: 'Nutri-Score' },
  { key: 'nova', label: 'NOVA group' },
  { key: 'quantity', label: 'Pack size' },
  { key: 'ingredients', label: 'Ingredients' },
  { key: 'categories', label: 'Categories' },
  { key: 'labels', label: 'Labels' },
];

/** A brand's score: how many of the seven things its products fill on average, from 0 to 7. */
export function scoreOf(row: BrandRow): number {
  return row.points / row.products;
}

/** The share (0 to 1) of a brand's products that fill one thing. */
export function shareOf(row: BrandRow, key: string): number {
  return row.filled[key] / row.products;
}

/** Half-point score bands from 0 to 7: 14 bands, the last one includes 7.0. */
export const BAND_COUNT = 14;

export function bandOf(score: number): number {
  return Math.min(BAND_COUNT - 1, Math.max(0, Math.floor(score * 2)));
}

export function bandLabel(band: number): string {
  return `${(band / 2).toFixed(1)} to ${((band + 1) / 2).toFixed(1)}`;
}

export interface Ranked {
  row: BrandRow;
  /** Place by score among every brand of the market; brands with the same score share a place (1, 2, 2, 4). */
  rank: number;
  score: number;
}

/** The brands of one market with their places, best score first (ties by name). */
export function rankBrands(rows: BrandRow[], market: Scope): Ranked[] {
  const own = rows
    .filter((row) => row.scope === market)
    .map((row) => ({ row, score: scoreOf(row) }))
    .sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));
  let rank = 0;
  return own.map((entry, i) => {
    if (i === 0 || entry.score !== own[i - 1].score) rank = i + 1;
    return { ...entry, rank };
  });
}

/** How many brands fall in each score band. */
export function histogram(ranked: Ranked[]): number[] {
  const counts = new Array<number>(BAND_COUNT).fill(0);
  for (const entry of ranked) counts[bandOf(entry.score)] += 1;
  return counts;
}

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Lower case, accents removed, so "Nestlé" is found by "nestle". */
export function plainText(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();
}

export type SortId = 'score-high' | 'score-low' | 'full-share' | 'most-share' | 'products' | 'name';

export const SORTS: { id: SortId; label: string }[] = [
  { id: 'score-high', label: 'Score, high to low' },
  { id: 'score-low', label: 'Score, low to high' },
  { id: 'full-share', label: 'Products filling all 7, highest share first' },
  { id: 'most-share', label: 'Products filling 5 or more, highest share first' },
  { id: 'products', label: 'Products held, most first' },
  { id: 'name', label: 'Brand name, A to Z' },
];

/** The two orders that need the eight product groups: the share of a brand's products that fill all 7, and the share that fill 5 or more. */
export const SPREAD_SORTS: SortId[] = ['full-share', 'most-share'];

/** The share (0 to 1) of a brand's products that fill at least `atLeast` of the seven things; null while the file has no product groups. */
export function shareFilling(row: BrandRow, atLeast: number): number | null {
  if (!row.spread) return null;
  return row.spread.slice(atLeast).reduce((sum, count) => sum + count, 0) / row.products;
}

/** The rows to show: those in the chosen band (if any) whose name holds the search text, in the chosen order. */
export function visibleBrands(ranked: Ranked[], band: number | null, query: string, sort: SortId): Ranked[] {
  const needle = plainText(query);
  const kept = ranked.filter((entry) => (band === null || bandOf(entry.score) === band) && (needle === '' || plainText(entry.row.name).includes(needle)));
  const byName = (a: Ranked, b: Ranked) => a.row.name.localeCompare(b.row.name);
  switch (sort) {
    case 'score-low':
      return kept.sort((a, b) => a.score - b.score || byName(a, b));
    case 'full-share':
    case 'most-share': {
      const atLeast = sort === 'full-share' ? 7 : 5;
      const share = (entry: Ranked) => shareFilling(entry.row, atLeast) ?? 0;
      return kept.sort((a, b) => share(b) - share(a) || b.score - a.score || byName(a, b));
    }
    case 'products':
      return kept.sort((a, b) => b.row.products - a.row.products || byName(a, b));
    case 'name':
      return kept.sort(byName);
    default:
      return kept.sort((a, b) => b.score - a.score || byName(a, b));
  }
}

/** One plain sentence about the market's brands, computed from the file and saying nothing the numbers do not show. */
export function brandsSentence(ranked: Ranked[], market: Scope): string {
  if (ranked.length === 0) return '';
  const scores = ranked.map((entry) => entry.score);
  const where = market === 'india' ? 'in India' : 'across all markets';
  const typical = median(scores).toFixed(1);
  return `${ranked.length} brands ${where} have 30 or more products. The typical brand fills ${typical} of the 7 things; the highest fills ${Math.max(...scores).toFixed(1)} and the lowest ${Math.min(...scores).toFixed(1)}.`;
}

export interface SpreadLine {
  /** How many of the seven things these products fill. */
  filledCount: number;
  products: number;
  /** Share of the brand's products, 0 to 1. */
  share: number;
}

/** The brand's products grouped by how many of the seven things they fill, fullest first. Null while the file has no such columns. */
export function spreadLines(row: BrandRow): SpreadLine[] | null {
  if (!row.spread) return null;
  const lines = row.spread.map((products, filledCount) => ({ filledCount, products, share: products / row.products }));
  return lines.reverse();
}

/** One plain sentence on a brand's spread: how many fill all seven, and how many fill five or more. */
export function spreadSentence(row: BrandRow): string | null {
  if (!row.spread) return null;
  const all = row.spread[7];
  const mostly = row.spread.slice(5).reduce((sum, count) => sum + count, 0);
  const share = (count: number) => `${Math.round((count / row.products) * 100)}%`;
  const products = (count: number) => `${count} ${count === 1 ? 'product' : 'products'}`;
  return `${products(all)} of ${row.products} (${share(all)}) fill all 7 things, and ${products(mostly)} (${share(mostly)}) fill 5 or more.`;
}
