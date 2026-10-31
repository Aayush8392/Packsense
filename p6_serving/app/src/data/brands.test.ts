import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseCsv } from './csv';
import { ITEMS, bandLabel, bandOf, brandsSentence, histogram, median, plainText, rankBrands, scoreOf, shareFilling, spreadLines, spreadSentence, visibleBrands } from './brands';
import { DataError, parseBrandScorecard } from './siteData';
import { withSpread } from './fixtures/withSpread';

// The real scorecard as published on 30 Oct 2026 (583 brands across all markets, 87 in India), every brand with 30 or more products.
const text = readFileSync(join(import.meta.dirname, 'fixtures', 'brand_scorecard.sample.csv'), 'utf-8');
const rows = parseBrandScorecard(text);

describe('the brand scorecard file', () => {
  it('reads every row, with the seven counts under the keys the page uses', () => {
    expect(rows).toHaveLength(parseCsv(text).length);
    expect(rows.filter((r) => r.scope === 'all')).toHaveLength(583);
    expect(rows.filter((r) => r.scope === 'india')).toHaveLength(87);
    expect(Object.keys(rows[0].filled)).toEqual(ITEMS.map((item) => item.key));
  });

  it("agrees with the file's own total: the seven counts add up to coverage_points on every brand", () => {
    for (const row of rows) expect(Object.values(row.filled).reduce((a, b) => a + b, 0), row.name).toBe(row.points);
  });

  it('refuses a file with a column missing, a count that is not a number, or a thing filled for more products than the brand has', () => {
    const header = text.split('\n')[0];
    const first = text.split('\n')[1];
    expect(() => parseBrandScorecard(text.replace('n_with_labels', 'n_with_label'))).toThrow(DataError);
    expect(() => parseBrandScorecard(`${header}\n${first.replace(/^([^,]*,[^,]*,[^,]*,)[^,]*/, '$1x')}\n`)).toThrow(/not a number/);
    const cells = first.split(',');
    cells[4] = String(Number(cells[3]) + 1);
    expect(() => parseBrandScorecard(`${header}\n${cells.join(',')}\n`)).toThrow(/more products than it has/);
  });
});

describe('scores and bands', () => {
  it('scores a brand as the average number of the seven things its products fill', () => {
    const row = rows.find((r) => r.scope === 'all' && r.name === '1664');
    expect(row && scoreOf(row)).toBe(6); // 180 points over 30 products
  });

  it('puts a score in a half-point band, with 7.0 in the last band', () => {
    expect([0, 0.49, 0.5, 3.99, 4, 6.99, 7].map(bandOf)).toEqual([0, 0, 1, 7, 8, 13, 13]);
    expect(bandLabel(9)).toBe('4.5 to 5.0');
  });

  it('counts every brand of the market in exactly one band', () => {
    for (const market of ['all', 'india'] as const) {
      const ranked = rankBrands(rows, market);
      const counts = histogram(ranked);
      expect(counts).toHaveLength(14);
      expect(counts.reduce((a, b) => a + b, 0)).toBe(ranked.length);
    }
    expect(histogram(rankBrands(rows, 'india'))).toEqual([0, 3, 2, 8, 10, 10, 15, 11, 15, 8, 5, 0, 0, 0]);
  });
});

describe('ranking, filtering and search', () => {
  const ranked = rankBrands(rows, 'all');

  it('places the best score first, and brands with the same score share a place', () => {
    expect(ranked[0].rank).toBe(1);
    expect(ranked[0].row.name).toBe('sodebo');
    for (const [i, entry] of ranked.entries()) {
      const higher = ranked.filter((other) => other.score > entry.score).length;
      expect(entry.rank, entry.row.name).toBe(higher + 1);
      if (i > 0) expect(ranked[i - 1].score).toBeGreaterThanOrEqual(entry.score);
    }
  });

  it('keeps only the brands of the chosen band, and the band counts agree with the list', () => {
    const counts = histogram(ranked);
    for (const band of [0, 7, 13]) expect(visibleBrands(ranked, band, '', 'score-high')).toHaveLength(counts[band]);
  });

  it('finds a brand whatever the case or accents, and combines the search with the band', () => {
    expect(plainText('  Nestlé ')).toBe('nestle');
    const found = visibleBrands(ranked, null, 'NESTLE', 'name').map((e) => e.row.name);
    expect(found).toContain('nestle');
    expect(found.every((name) => plainText(name).includes('nestle'))).toBe(true);
    expect(visibleBrands(ranked, 13, 'nestle', 'name').every((e) => bandOf(e.score) === 13)).toBe(true);
    expect(visibleBrands(ranked, null, 'zzzz-no-such-brand', 'name')).toEqual([]);
  });

  it('orders by score either way, by products held and by name', () => {
    const low = visibleBrands(ranked, null, '', 'score-low');
    expect(low[0].score).toBe(Math.min(...ranked.map((e) => e.score)));
    const many = visibleBrands(ranked, null, '', 'products');
    expect(many[0].row.products).toBe(Math.max(...ranked.map((e) => e.row.products)));
    const names = visibleBrands(ranked, null, '', 'name').map((e) => e.row.name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });

  it('writes one sentence from the numbers', () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
    const sentence = brandsSentence(ranked, 'all');
    expect(sentence).toContain('583 brands across all markets have 30 or more products');
    expect(sentence).toContain('highest fills 6.9');
    expect(sentence).toContain('lowest 0.0');
    expect(brandsSentence(rankBrands(rows, 'india'), 'india')).toContain('87 brands in India');
    expect(brandsSentence([], 'all')).toBe('');
  });
});

const NL = String.fromCharCode(10);

describe('how complete the products of a brand are', () => {
  const full = parseBrandScorecard(withSpread(text));

  it('leaves the details out of a file that has no such columns, and reads them from one that has', () => {
    expect(rows.every((row) => row.spread === null)).toBe(true);
    expect(spreadLines(rows[0])).toBeNull();
    expect(spreadSentence(rows[0])).toBeNull();
    expect(full.every((row) => row.spread !== null)).toBe(true);
  });

  it('keeps the eight counts equal to the products of the brand and, weighted 0 to 7, to its points', () => {
    for (const row of full) {
      const spread = row.spread as number[];
      expect(spread.reduce((a, b) => a + b, 0), row.name).toBe(row.products);
      expect(spread.reduce((sum, count, i) => sum + count * i, 0), row.name).toBe(row.points);
    }
  });

  it('refuses a file whose groups do not add up', () => {
    const lines = withSpread(text).trim().split(NL);
    const cells = lines[1].split(',');
    cells[cells.length - 1] = String(Number(cells[cells.length - 1]) + 1);
    expect(() => parseBrandScorecard([lines[0], cells.join(','), ...lines.slice(2)].join(NL))).toThrow(/do not add up/);
    const moved = lines[1].split(',');
    const n = moved.length;
    // one product moved from one count to the next keeps the total but changes the points
    const i = moved.slice(n - 8).findIndex((value) => Number(value) > 0);
    moved[n - 8 + i] = String(Number(moved[n - 8 + i]) - 1);
    moved[n - 8 + ((i + 1) % 8)] = String(Number(moved[n - 8 + ((i + 1) % 8)]) + 1);
    expect(() => parseBrandScorecard([lines[0], moved.join(','), ...lines.slice(2)].join(NL))).toThrow(/do not match its points/);
  });

  it('lists the counts fullest first and says it in one sentence', () => {
    const row = full.find((entry) => entry.name === '1664')!; // 30 products, 180 points: every one fills six
    const lines = spreadLines(row)!;
    expect(lines.map((line) => line.filledCount)).toEqual([7, 6, 5, 4, 3, 2, 1, 0]);
    expect(lines.find((line) => line.filledCount === 6)).toMatchObject({ products: 30, share: 1 });
    expect(spreadSentence(row)).toBe('0 products of 30 (0%) fill all 7 things, and 30 products (100%) fill 5 or more.');
  });

  it('orders by the share of products that fill all 7, or 5 or more, and writes no share without the columns', () => {
    const ranked = rankBrands(full, 'all');
    const byFull = visibleBrands(ranked, null, '', 'full-share').map((entry) => shareFilling(entry.row, 7) as number);
    expect(byFull).toEqual([...byFull].sort((a, b) => b - a));
    const byMost = visibleBrands(ranked, null, '', 'most-share').map((entry) => shareFilling(entry.row, 5) as number);
    expect(byMost).toEqual([...byMost].sort((a, b) => b - a));
    expect(shareFilling(rows[0], 7)).toBeNull();
    expect(shareFilling(full.find((entry) => entry.name === '1664')!, 5)).toBe(1);
  });
});
