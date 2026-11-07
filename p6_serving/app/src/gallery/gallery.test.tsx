import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { parseBrandScorecard, parseCategoryFitness, parseChangeDaily, parseNutritionSources, parseQualityDaily, parseRuleChecks } from '../data/siteData';
import { formatCount } from '../format';
import { ChartGallery } from './ChartGallery';
import { buildGallery, changeWords, dayNumber, median, percent, startIndex, weekOverWeek, weekdayOf, type BarChartSpec, type GalleryData, type LineChartSpec } from './charts';

afterEach(cleanup);

// Real rows of the published files (1 to 15 Oct 2026), taken from the gold fixture the export tests use. The expected numbers below are
// computed here again from the raw CSV text, not from the code under test.
const read = (name: string) => readFileSync(join(import.meta.dirname, '..', 'data', 'fixtures', name), 'utf-8');
const qualityText = read('quality_daily.sample.csv');
const changeText = read('change_daily.sample.csv');
const brandText = read('brand_scorecard.sample.csv');
const categoryText = read('category_fitness.real.csv');
const ruleText = read('rule_checks.real.csv');
const sourceText = read('nutrition_sources.real.csv');
const data: GalleryData = {
  quality: parseQualityDaily(qualityText),
  change: parseChangeDaily(changeText),
  brands: parseBrandScorecard(brandText),
  categories: parseCategoryFitness(categoryText),
  rules: parseRuleChecks(ruleText),
  sources: parseNutritionSources(sourceText),
};

const table = (text: string) => {
  const [head, ...lines] = text.trim().split('\n');
  const names = head.split(',');
  return lines.map((line) => Object.fromEntries(line.split(',').map((cell, i) => [names[i], cell])) as Record<string, string>);
};
const quality = table(qualityText);
const change = table(changeText);
const brands = table(brandText);

describe('buildGallery', () => {
  it('builds all ten charts in a fixed order for each market', () => {
    const ids = ['flag-flow', 'family-change', 'kind-share', 'weekday-edits', 'india-share', 'empty-fields', 'size-bands', 'thin-categories', 'rule-checks', 'nutrition-sources'];
    expect(buildGallery(data, 'all').map((c) => c.id)).toEqual(ids);
    // India's daily counts are small and often hidden (1 to 4), so a chart that needs a full run of known days can drop out; the order never changes.
    const india = buildGallery(data, 'india').map((c) => c.id);
    expect(india.length).toBeGreaterThanOrEqual(5);
    expect(india).toEqual(ids.filter((id) => india.includes(id)));
    expect(india).not.toContain('weekday-edits');
  });

  it('leaves a chart out when its figures are missing, and never draws from a guess', () => {
    expect(buildGallery({ quality: [], change: [], brands: [] }, 'all')).toEqual([]);
    const noBrands = buildGallery({ ...data, brands: [] }, 'all').map((c) => c.id);
    expect(noBrands).not.toContain('empty-fields');
    expect(noBrands).not.toContain('size-bands');
  });
});

describe('flags that appeared and ended', () => {
  const chart = buildGallery(data, 'all')[0] as LineChartSpec;
  const perDay = (column: string, day: string) => quality.filter((r) => r.scope === 'all' && r.snapshot_date === day).reduce((s, r) => s + (r[column] === '' ? 0 : Number(r[column])), 0);

  it('adds every severity and kind for each day', () => {
    const appeared = chart.series[0].points;
    expect(appeared[appeared.length - 1]).toEqual({ day: '2026-10-15', value: perDay('opened_on_known_product', '2026-10-15') });
    const ended = chart.series[1].points;
    expect(ended[ended.length - 1].value).toBe(perDay('vanished', '2026-10-15'));
  });

  it('writes the caption from the last 7 days against the 7 before', () => {
    const days = Array.from({ length: 14 }, (_, i) => `2026-10-${String(i + 2).padStart(2, '0')}`);
    const recent = days.slice(7).reduce((s, d) => s + perDay('opened_on_known_product', d), 0);
    const before = days.slice(0, 7).reduce((s, d) => s + perDay('opened_on_known_product', d), 0);
    expect(chart.caption).toContain(`at least ${formatCount(recent)} flags appeared`);
    expect(chart.caption).toContain(changeWords(recent, before));
    expect(chart.caption).toContain('ended');
  });
});

describe('week against week', () => {
  it('needs 14 days, then compares the newest 7 with the 7 before', () => {
    const points = Array.from({ length: 14 }, (_, i) => ({ day: `2026-10-${String(i + 1).padStart(2, '0')}`, value: i < 7 ? 10 : 12 }));
    expect(weekOverWeek(points.slice(1))).toBeNull();
    expect(weekOverWeek(points)).toEqual({ recent: 84, before: 70 });
  });

  it('words the change: up, down, about the same, or up from none', () => {
    expect(changeWords(112, 100)).toBe('up 12%');
    expect(changeWords(96, 100)).toBe('down 4%');
    expect(changeWords(100, 100)).toBe('about the same');
    expect(changeWords(1005, 1000)).toBe('about the same');
    expect(changeWords(5, 0)).toBe('up from none');
    expect(changeWords(0, 0)).toBe('about the same');
  });

  it('writes a percent with a decimal below 10%', () => {
    expect(percent(0.034)).toBe('3.4%');
    expect(percent(0.125)).toBe('13%');
    expect(percent(0)).toBe('0%');
  });
});

describe('kinds of flag that changed most', () => {
  const chart = buildGallery(data, 'all')[1] as BarChartSpec;
  const open = (day: string) => {
    const byFamily = new Map<string, number>();
    for (const r of quality.filter((q) => q.scope === 'all' && q.snapshot_date === day)) byFamily.set(r.flag_family, (byFamily.get(r.flag_family) ?? 0) + (r.open_spans === '' ? NaN : Number(r.open_spans)));
    return byFamily;
  };

  it('ranks by the size of the move between the first and the newest day, a blanked end left out', () => {
    const now = open('2026-10-15');
    const then = open('2026-10-01');
    const moves = [...now.entries()]
      .map(([family, to]) => ({ family, change: to - (then.get(family) ?? 0) }))
      .filter((m) => !Number.isNaN(m.change))
      .sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
    expect(chart.rows).toHaveLength(Math.min(8, moves.length));
    expect(chart.rows[0].value).toBe(moves[0].change);
    expect(chart.rows.map((r) => Math.abs(r.value as number))).toEqual([...chart.rows.map((r) => Math.abs(r.value as number))].sort((a, b) => b - a));
    expect(chart.caption).toContain('over 14 days');
  });
});

describe('what kind of edit products get', () => {
  const chart = buildGallery(data, 'all')[2] as LineChartSpec;

  it('shows the four most common kinds as shares of the edited products, never more than 100% each', () => {
    expect(chart.series).toHaveLength(4);
    for (const series of chart.series) for (const p of series.points) if (p.value !== null) expect(p.value).toBeLessThanOrEqual(1);
  });

  it('a share is the kind\'s products over the products edited that day', () => {
    const day = '2026-10-15';
    const pick = (group: string) => Number(change.find((r) => r.scope === 'all' && r.change_date === day && r.change_group === group)?.n_products ?? 0);
    const first = chart.series[0];
    const last = first.points[first.points.length - 1].value as number;
    expect(last).toBeCloseTo(pick(first.id) / pick('any'), 9);
  });

  it('says that the kinds overlap', () => {
    expect(chart.note).toContain('more than 100%');
  });
});

describe('edits by day of the week', () => {
  const chart = buildGallery(data, 'all')[3] as BarChartSpec;

  it('lists Monday to Sunday', () => {
    expect(chart.rows.map((r) => r.label)).toEqual(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']);
  });

  it('compares each day with the median of the 7 days around it, then takes the median per weekday', () => {
    expect(weekdayOf('2026-10-05')).toBe(1);
    const daily = change.filter((r) => r.scope === 'all' && r.change_group === 'any').sort((a, b) => a.change_date.localeCompare(b.change_date));
    const values = daily.map((r) => Number(r.n_products));
    const expected: Record<number, number[]> = {};
    for (let i = 3; i < values.length - 3; i++) {
      const base = median(values.slice(i - 3, i + 4));
      (expected[weekdayOf(daily[i].change_date)] ??= []).push(values[i] / base);
    }
    const mondayRatio = median(expected[1]);
    expect(chart.rows[0].value).toBeCloseTo((mondayRatio - 1) * 100, 9);
    expect(chart.rows[0].display).toBe(`${mondayRatio >= 1 ? '+' : '−'}${Math.abs(Math.round((mondayRatio - 1) * 100))}%`);
  });

  it('the median ignores one huge day (the middle of 1, 2, 3, 4 and 900 is 3)', () => {
    expect(median([1, 900, 3, 4, 2])).toBe(3);
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });

  it('draws bars either side of a centre line and says the comparison is from a few days each', () => {
    expect(chart.note).toContain('median of the 7 days around it');
    expect(chart.rows.some((r) => (r.value as number) < 0)).toBe(true);
  });
});

describe("India's share of all edits", () => {
  const chart = buildGallery(data, 'all')[4] as LineChartSpec;

  it("is India's edited products over all edited products, per day", () => {
    const day = '2026-10-15';
    const get = (scope: string) => Number(change.find((r) => r.scope === scope && r.change_date === day && r.change_group === 'any')?.n_products);
    const points = chart.series[0].points;
    expect(points[points.length - 1].value).toBeCloseTo(get('india') / get('all'), 9);
  });

  it('is the same chart whichever market is chosen', () => {
    const india = buildGallery(data, 'india').find((c) => c.id === 'india-share') as LineChartSpec;
    expect(india.series[0].points).toEqual(chart.series[0].points);
  });
});

describe('the fields brands leave empty', () => {
  const chart = buildGallery(data, 'all')[5] as BarChartSpec;
  const own = brands.filter((b) => b.scope === 'all');
  const total = own.reduce((s, b) => s + Number(b.n_products), 0);

  it('shares the missing products of each of the seven things, the emptiest first', () => {
    expect(chart.rows).toHaveLength(7);
    const values = chart.rows.map((r) => r.value as number);
    expect(values).toEqual([...values].sort((a, b) => b - a));
    const nutrition = chart.rows.find((r) => r.id === 'nutrition');
    expect(nutrition?.value).toBeCloseTo((1 - own.reduce((s, b) => s + Number(b.n_with_nutrition), 0) / total) * 100, 9);
  });

  it('says the file has only brands with at least 30 products', () => {
    expect(chart.note).toContain('at least 30 products');
    expect(chart.note).toContain(formatCount(total));
  });
});

describe('brand size and completeness', () => {
  const chart = buildGallery(data, 'all')[6] as BarChartSpec;

  it('averages the points per product within each size band, each product counted once', () => {
    const band = (from: number, to: number) => brands.filter((b) => b.scope === 'all' && Number(b.n_products) >= from && Number(b.n_products) <= to);
    const expected = (rows: Record<string, string>[]) => rows.reduce((s, b) => s + Number(b.coverage_points), 0) / rows.reduce((s, b) => s + Number(b.n_products), 0);
    const first = chart.rows.find((r) => r.id === '30-49');
    expect(first?.value).toBeCloseTo(expected(band(30, 49)), 9);
    const brandCounts = chart.rows.map((r) => Number(r.small?.split(' ')[0].replace(',', '')));
    expect(brandCounts.reduce((s, n) => s + n, 0)).toBeLessThanOrEqual(brands.filter((b) => b.scope === 'all').length);
  });
});

describe('the opening chart rotates by day number', () => {
  it('is the same all day and moves one chart each day on the India clock', () => {
    const morning = new Date('2026-11-07T04:00:00Z');
    const evening = new Date('2026-11-07T18:00:00Z'); // 23:30 IST, still the same India day
    const next = new Date('2026-11-07T18:30:00Z'); // 00:00 IST on 8 Nov
    expect(startIndex(morning, 7)).toBe(startIndex(evening, 7));
    expect(dayNumber(next)).toBe(dayNumber(morning) + 1);
    expect(startIndex(next, 7)).toBe((startIndex(morning, 7) + 1) % 7);
  });

  it('shows every chart once in any run of seven days', () => {
    const shown = new Set(Array.from({ length: 7 }, (_, i) => startIndex(new Date(Date.UTC(2026, 10, 7 + i, 6)), 7)));
    expect(shown.size).toBe(7);
  });
});

describe('the carousel', () => {
  const now = new Date('2026-11-07T06:00:00Z');
  const N = 10;                                             // seven charts of the first batch and the three that came with the later files
  const start = startIndex(now, N);

  it('opens on the chart of the day and says which of the seven it is', () => {
    render(<ChartGallery data={data} market="all" now={now} />);
    expect(screen.getByText(`Chart ${start + 1} of ${N}`)).toBeTruthy();
    const slide = screen.getByRole('group', { name: new RegExp(`^${start + 1} of ${N}`) });
    expect(within(slide).getAllByRole('heading', { level: 3 })).toHaveLength(1);
  });

  it('moves with Next and Previous, and wraps round the ends', () => {
    render(<ChartGallery data={data} market="all" now={now} />);
    fireEvent.click(screen.getByRole('button', { name: /Next chart/ }));
    expect(screen.getByText(`Chart ${((start + 1) % N) + 1} of ${N}`)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Previous chart/ }));
    fireEvent.click(screen.getByRole('button', { name: /Previous chart/ }));
    expect(screen.getByText(`Chart ${((start + N - 1) % N) + 1} of ${N}`)).toBeTruthy();
  });

  it('lists every chart by name and jumps to the one chosen', () => {
    render(<ChartGallery data={data} market="all" now={now} />);
    const catalogue = screen.getByRole('list', { name: 'All the charts' });
    const tabs = within(catalogue).getAllByRole('button');
    expect(tabs).toHaveLength(N);
    fireEvent.click(tabs[3]);
    expect(screen.getByText(`Chart 4 of ${N}`)).toBeTruthy();
    expect(tabs[3].getAttribute('aria-current')).toBe('true');
    expect(screen.getByRole('heading', { level: 3, name: 'Edits by day of the week' })).toBeTruthy();
  });

  it('shows the very same numbers as a table, for a bar chart and for a line chart', () => {
    render(<ChartGallery data={data} market="all" now={now} />);
    const tabs = within(screen.getByRole('list', { name: 'All the charts' })).getAllByRole('button');
    fireEvent.click(tabs[5]); // fields left empty: bars
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(8);
    fireEvent.click(tabs[0]); // flags: lines
    fireEvent.click(screen.getByRole('button', { name: 'Show as a table' }));
    expect(screen.getByRole('table')).toBeTruthy();
  });

  it('draws nothing when no chart can be built', () => {
    const { container } = render(<ChartGallery data={{ quality: [], change: [], brands: [] }} market="all" now={now} />);
    expect(container.firstChild).toBeNull();
  });
});

// --- the three charts of the later files: categories, arithmetic checks and nutrition sources --------------------------------------------------------

describe('categories where the data is thin', () => {
  const chart = buildGallery(data, 'all').find((c) => c.id === 'thin-categories') as BarChartSpec;
  const raw = table(categoryText).filter((r) => r.scope === 'all');

  it('lists the eight categories with the smallest share of products that carry all five core nutrients, the thinnest first', () => {
    const shares = raw.map((r) => ({ category: r.category, share: Number(r.n_five_nutrients) / Number(r.n_products) })).sort((a, b) => a.share - b.share);
    expect(chart.rows).toHaveLength(8);
    expect(chart.rows.map((r) => r.id)).toEqual(shares.slice(0, 8).map((s) => s.category));
    expect(chart.rows[0].value).toBeCloseTo(shares[0].share * 100, 9);
    expect(chart.caption).toContain(`${formatCount(Number(raw.find((r) => r.category === shares[0].category)?.n_products))} products carry all five`);
  });

  it('counts the ranked categories in its note and names the first category rule', () => {
    expect(chart.note).toContain(`${raw.length} top-level categories with at least 200 products`);
    expect(chart.note).toContain('first category listed');
  });

  it('is left out when fewer than three ranked categories are known', () => {
    const few = parseCategoryFitness(categoryText).filter((c) => c.scope === 'all').slice(0, 2);
    expect(buildGallery({ ...data, categories: few }, 'all').map((c) => c.id)).not.toContain('thin-categories');
  });
});

describe('which checks flag the largest share of products', () => {
  const rows = table(ruleText).filter((r) => r.scope === 'all');

  it('lists every rule that was checked, with the flagged share, the biggest first, and a hidden count has no bar', () => {
    const chart = buildGallery(data, 'all').find((c) => c.id === 'rule-checks') as BarChartSpec;
    expect(chart.rows).toHaveLength(rows.length);
    const hidden = rows.filter((r) => r.n_products_flagged === '').map((r) => r.rule);
    for (const id of hidden) expect(chart.rows.find((r) => r.id === id)?.value).toBeNull();
    const known = chart.rows.filter((r) => r.value !== null).map((r) => r.value as number);
    expect(known).toEqual([...known].sort((a, b) => b - a));
  });

  it('words it as flagged, never as wrong', () => {
    const chart = buildGallery(data, 'all').find((c) => c.id === 'rule-checks') as BarChartSpec;
    expect(chart.note).toContain('flag is not a verdict that the number is wrong');
    expect(`${chart.title} ${chart.caption}`.toLowerCase()).not.toMatch(/\bwrong\b|\bincorrect\b/);
  });

  it('shows the flagged share from the real counts when none is hidden', () => {
    const open = parseRuleChecks('scope,rule,n_products_checked,n_products_flagged\nall,salt-does-not-match-sodium,200,50\nall,value-over-105,100,10\n');
    const chart = buildGallery({ ...data, rules: open }, 'all').find((c) => c.id === 'rule-checks') as BarChartSpec;
    expect(chart.rows[0].id).toBe('salt-does-not-match-sodium');
    expect(chart.rows[0].value).toBeCloseTo(25, 9);
    expect(chart.rows[0].display).toBe('25% (50 of 200)');
    expect(chart.caption).toContain('50 of the 200 products');
  });
});

describe('where nutrition numbers come from', () => {
  const rows = table(sourceText).filter((r) => r.scope === 'all');
  const total = rows.reduce((s, r) => s + Number(r.n_sets), 0);

  it('shows each source as a share of all the nutrition tables, the biggest first, with the pack, the maker and the estimate named in words', () => {
    const chart = buildGallery(data, 'all').find((c) => c.id === 'nutrition-sources') as BarChartSpec;
    expect(chart.rows).toHaveLength(rows.length);
    const packaging = chart.rows.find((r) => r.id === 'packaging');
    expect(packaging?.value).toBeCloseTo((Number(rows.find((r) => r.source === 'packaging')?.n_sets) / total) * 100, 9);
    expect(packaging?.label).toBe('Printed on the pack');
    expect(chart.rows.find((r) => r.id === 'estimate')?.label).toBe("Open Food Facts' own estimate");
    const values = chart.rows.map((r) => r.value as number);
    expect(values).toEqual([...values].sort((a, b) => b - a));
    expect(chart.note).toContain(formatCount(total));
  });

  it('says how much is an estimate when the biggest source is something else', () => {
    const chart = buildGallery(data, 'all').find((c) => c.id === 'nutrition-sources') as BarChartSpec;
    expect(chart.caption).toMatch(/are Open Food Facts' own estimates/);
  });
});

describe('the caption of the checks chart', () => {
  it('quotes the name of the most flagged check once, with its closing full stop moved outside the quote', () => {
    const chart = buildGallery(data, 'all').find((c) => c.id === 'rule-checks') as BarChartSpec;
    expect(chart.caption).toMatch(/^The largest share of flagged products is for the check "[^"]+[^."]"\. It flags /);
  });
});
