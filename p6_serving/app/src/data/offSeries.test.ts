import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { formatCompact } from '../format';
import { flagMoves, openBySeverity, topOpenKinds, weeklyPoints } from './offSeries';
import { OFF_OTHER_KIND, parseOffOpenFlags, parseOffWeekly } from './siteData';

// The two files as the publish job writes them, from the rows production built on 7 Nov 2026 (the fixture of the export tests).
const read = (name: string) => readFileSync(join(import.meta.dirname, 'fixtures', name), 'utf-8');
const weeklyText = read('off_weekly.real.csv');
const openText = read('off_open_flags.real.csv');
const weekly = parseOffWeekly(weeklyText);
const open = parseOffOpenFlags(openText);

const lines = (text: string) => text.trim().split('\n').slice(1).map((l) => l.split(','));

describe('the whole-OFF weekly file', () => {
  it('has 32 weeks, oldest 29 Mar and newest 1 Nov 2026, one row per week', () => {
    expect(weekly).toHaveLength(32);
    const days = weeklyPoints(weekly, (r) => r.productsHeld).map((p) => p.day);
    expect(days[0]).toBe('2026-03-29');
    expect(days[days.length - 1]).toBe('2026-11-01');
    expect(new Set(days).size).toBe(32);
  });

  it('adds the three severities for "all flags" and takes the error column alone for "errors only" (1 Nov: 27,348 + 17,662 + 408 ended)', () => {
    const raw = lines(weeklyText).find((r) => r[0] === '2026-11-01') as string[];
    const all = flagMoves(weekly, 'ended', 'all');
    const errors = flagMoves(weekly, 'ended', 'error');
    expect(all[all.length - 1].value).toBe(Number(raw[5]) + Number(raw[6]) + Number(raw[7]));
    expect(errors[errors.length - 1].value).toBe(Number(raw[5]));
    const appeared = flagMoves(weekly, 'appeared', 'all');
    expect(appeared[appeared.length - 1].value).toBe(Number(raw[8]) + Number(raw[9]) + Number(raw[10]));
  });

  it('a hidden count (1 to 4) is a gap in a single column and adds nothing to a sum', () => {
    const hidden = parseOffWeekly('week_end,products_held,products_added,products_removed,products_edited,flags_ended_error,flags_ended_warning,flags_ended_info,flags_appeared_error,flags_appeared_warning,flags_appeared_info\n2026-11-01,4887851,54190,,36764,,27348,17662,1380,20763,11558\n');
    expect(weeklyPoints(hidden, (r) => r.productsRemoved)[0].value).toBeNull();
    expect(flagMoves(hidden, 'ended', 'error')[0].value).toBeNull();
    expect(flagMoves(hidden, 'ended', 'all')[0].value).toBe(27348 + 17662);
  });

  it('refuses a file with a column missing', () => {
    expect(() => parseOffWeekly('week_end,products_held\n2026-11-01,1\n')).toThrow(/missing the column/);
  });
});

describe('the whole-OFF open flags file', () => {
  it('adds every kind of one severity at each snapshot: 261,383 error flags on 1 Nov, 241,024 on 22 Mar', () => {
    const errors = openBySeverity(open, 'error');
    expect(errors).toHaveLength(33);
    expect(errors[0]).toEqual({ day: '2026-03-22', value: 241_024 });
    expect(errors[errors.length - 1]).toEqual({ day: '2026-11-01', value: 261_383 });
    const sum = lines(openText).filter((r) => r[0] === '2026-11-01' && r[1] === 'warning').reduce((s, r) => s + Number(r[3]), 0);
    expect(openBySeverity(open, 'warning').pop()?.value).toBe(sum);
  });

  it('ranks the kinds on the newest snapshot, leaves out the row that adds up the small ones, and carries each kind\'s oldest count', () => {
    const top = topOpenKinds(open, 8);
    expect(top?.newest).toBe('2026-11-01');
    expect(top?.oldest).toBe('2026-03-22');
    expect(top?.kinds).toHaveLength(8);
    expect(top?.kinds.every((k) => k.kind !== OFF_OTHER_KIND)).toBe(true);
    const counts = (top?.kinds ?? []).map((k) => k.now);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
    const lead = top?.kinds[0] as { severity: string; kind: string; now: number; first: number };
    const row = lines(openText).find((r) => r[0] === '2026-11-01' && r[1] === lead.severity && r[2] === lead.kind) as string[];
    expect(lead.now).toBe(Number(row[3]));
    const old = lines(openText).find((r) => r[0] === '2026-03-22' && r[1] === lead.severity && r[2] === lead.kind);
    expect(lead.first).toBe(old ? Number(old[3]) : 0);
  });

  it('has no ranking with fewer than two snapshots', () => {
    expect(topOpenKinds(open.filter((r) => r.day === '2026-11-01'), 8)).toBeNull();
  });
});

describe('short numbers for a chart axis', () => {
  it.each([
    [0, '0'],
    [950, '950'],
    [4_200, '4.2k'],
    [12_400, '12k'],
    [261_383, '261k'],
    [4_887_851, '4.89M'],
    [22_458_911, '22.5M'],
    [4_000_000, '4M'],
  ])('%d is written %s', (value, text) => {
    expect(formatCompact(value)).toBe(text);
  });
});
