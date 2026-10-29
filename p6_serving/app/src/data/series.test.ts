import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { flagName, readableTag } from './flagNames';
import { KINDS, changeSeries, dayRange, flagsPerProduct, kindsOnDay, productsHeld, qualityDays, topFamilies } from './series';
import { parseChangeDaily, parseQualityDaily, type QualityRow } from './siteData';

// Real rows of the published files (1 to 15 Oct 2026), taken from the gold fixture the export tests use.
const fixture = (name: string) => readFileSync(join(import.meta.dirname, 'fixtures', name), 'utf-8');
const quality = parseQualityDaily(fixture('quality_daily.sample.csv'));
const changes = parseChangeDaily(fixture('change_daily.sample.csv'));

describe('quality figures', () => {
  it('reads the real file: 555 rows, 15 whole days, three severities, two markets', () => {
    expect(quality).toHaveLength(555);
    expect(qualityDays(quality, 'all')).toHaveLength(15);
    expect(new Set(quality.map((r) => r.severity))).toEqual(new Set(['error', 'warning', 'info']));
    expect(new Set(quality.map((r) => r.scope))).toEqual(new Set(['all', 'india']));
  });

  it('counts the products held each day', () => {
    const held = productsHeld(quality, 'all');
    expect(held[held.length - 1]).toEqual({ day: '2026-10-15', value: 233 });
    expect(held[0].value).toBeLessThan(held[held.length - 1].value as number);
  });

  it('divides open flags by products held (15 Oct: 29 errors, 1,134 warnings and 1,017 information flags on 233 products)', () => {
    const total = flagsPerProduct(quality, 'all', 'all');
    expect(total[total.length - 1].value).toBeCloseTo((29 + 1134 + 1017) / 233, 6);
    const errors = flagsPerProduct(quality, 'all', 'error');
    expect(errors[errors.length - 1].value).toBeCloseTo(29 / 233, 6);
  });

  it('adds nothing for a hidden count, so a figure is "at least"', () => {
    const rows: QualityRow[] = [
      { day: '2026-10-01', scope: 'all', severity: 'warning', family: 'a', openFlags: null, productsHeld: 10 },
      { day: '2026-10-01', scope: 'all', severity: 'warning', family: 'b', openFlags: 20, productsHeld: 10 },
    ];
    expect(flagsPerProduct(rows, 'all', 'all')[0].value).toBe(2);
  });

  it('ranks the kinds of flag by open flags and gives each its share (15 Oct: 893 of 2,180)', () => {
    const top = topFamilies(quality, 'all', '2026-10-15', 3);
    expect(top[0].family).toBe('en:environmental-score-quality-warnings');
    expect(top[0].flags).toBe(893);
    expect(top[0].share).toBeCloseTo(893 / 2180, 6);
    // OFF gives this kind of flag two severities (a known fact of the data), and the count adds both.
    expect(top[0].severities).toEqual(['warning', 'info']);
    expect(top.map((t) => t.flags)).toEqual([...top.map((t) => t.flags)].sort((a, b) => b - a));
  });

  it('gives an empty answer for a market with no rows', () => {
    expect(qualityDays([], 'india')).toEqual([]);
    expect(topFamilies([], 'all', '2026-10-15', 5)).toEqual([]);
  });
});

describe('change figures', () => {
  it('fills every calendar day, and treats a day with no row as no edits', () => {
    const edited = changeSeries(changes, 'india', 'any');
    expect(edited).toHaveLength(dayRange(edited[0].day, edited[edited.length - 1].day).length);
    expect(edited.some((p) => p.value === 0)).toBe(true);
  });

  it('reads the real counts (15 Oct: 13 products edited in all markets, 8 in India)', () => {
    const all = changeSeries(changes, 'all', 'any');
    expect(all[all.length - 1]).toEqual({ day: '2026-10-15', value: 13 });
    const india = changeSeries(changes, 'india', 'any', ['2026-10-15']);
    expect(india[0].value).toBe(8);
  });

  it('keeps a hidden count unknown instead of zero', () => {
    const hidden = parseChangeDaily('change_date,scope,change_group,opened_by_seed,n_products,n_periods,unseen_edits\n2026-10-01,all,any,0,,,0\n');
    expect(changeSeries(hidden, 'all', 'any')[0].value).toBeNull();
  });

  it('lists all eight kinds in the page order, which overlap and so are not summed', () => {
    const kinds = kindsOnDay(changes, 'all', '2026-10-15');
    expect(kinds.map((k) => k.group)).toEqual(KINDS.map((k) => k.group));
    expect(kinds).toHaveLength(8);
    const sum = kinds.reduce((total, k) => total + (k.products ?? 0), 0);
    const any = changeSeries(changes, 'all', 'any', ['2026-10-15'])[0].value as number;
    expect(sum).toBeGreaterThanOrEqual(any);
  });
});

describe('days and names', () => {
  it('builds a continuous range of days', () => {
    expect(dayRange('2026-10-30', '2026-11-02')).toEqual(['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02']);
  });

  it('makes an Open Food Facts tag readable and says it is not a plain name yet', () => {
    expect(readableTag('en:food-groups-warnings')).toBe('Food groups warnings');
    expect(flagName('en:food-groups-warnings')).toEqual({ name: 'Food groups warnings', plain: false });
    expect(flagName('unmapped').plain).toBe(true);
  });
});
