import { describe, expect, it } from 'vitest';
import { addDays } from '../format';
import { GRAIN_ORDER, grainsFrom, periodEnd, periodStart, rollUp } from './rollup';
import type { DayPoint } from './series';

function days(first: string, count: number, value: (i: number) => number | null = () => 1): DayPoint[] {
  return Array.from({ length: count }, (_, i) => ({ day: addDays(first, i), value: value(i) }));
}

describe('periods', () => {
  it('ends a week on its Sunday and a month on its last day', () => {
    expect(periodEnd('2026-10-01', 'week')).toBe('2026-10-04'); // a Thursday
    expect(periodEnd('2026-10-04', 'week')).toBe('2026-10-04'); // a Sunday ends its own week
    expect(periodEnd('2026-10-05', 'week')).toBe('2026-10-11'); // a Monday starts the next one
    expect(periodEnd('2026-02-10', 'month')).toBe('2026-02-28');
    expect(periodEnd('2028-02-10', 'month')).toBe('2028-02-29');
    expect(periodStart('2026-10-11', 'week')).toBe('2026-10-05');
    expect(periodStart('2026-10-31', 'month')).toBe('2026-10-01');
  });

  it('offers a chart its own grain and every coarser one', () => {
    expect(grainsFrom('day')).toEqual(GRAIN_ORDER);
    expect(grainsFrom('week')).toEqual(['week', 'month']);
    expect(grainsFrom('month')).toEqual(['month']);
  });
});

describe('rollUp', () => {
  const run = days('2026-10-01', 36); // Thu 1 Oct to Thu 5 Nov, one a day

  it('sums a flow by week and marks the first and last week as parts', () => {
    const weeks = rollUp(run, 'day', 'week', 'sum');
    expect(weeks.map((w) => w.day)).toEqual(['2026-10-04', '2026-10-11', '2026-10-18', '2026-10-25', '2026-11-01', '2026-11-08']);
    expect(weeks.map((w) => w.value)).toEqual([4, 7, 7, 7, 7, 4]);
    expect(weeks.map((w) => w.partial === true)).toEqual([true, false, false, false, false, true]);
  });

  it('sums a flow by month, and the month in progress is a part', () => {
    const months = rollUp(run, 'day', 'month', 'sum');
    expect(months).toEqual([
      { day: '2026-10-31', value: 31 },
      { day: '2026-11-30', value: 5, partial: true },
    ]);
  });

  it('keeps the last value of a level and the largest of a maximum', () => {
    const rising = days('2026-10-05', 14, (i) => i + 1); // Mon 5 Oct to Sun 18 Oct
    expect(rollUp(rising, 'day', 'week', 'last').map((w) => w.value)).toEqual([7, 14]);
    expect(rollUp(days('2026-10-05', 14, (i) => (i === 2 ? 50 : 1)), 'day', 'week', 'max').map((w) => w.value)).toEqual([50, 1]);
  });

  it('makes a period not known when one of its days is not known, never a total with a hole in it', () => {
    const holed = days('2026-10-05', 14, (i) => (i === 9 ? null : 1));
    expect(rollUp(holed, 'day', 'week', 'sum').map((w) => w.value)).toEqual([7, null]);
  });

  it('works out a ratio from its two sums, not from the daily ratios', () => {
    const num = [{ day: '2026-10-05', value: 1 }, { day: '2026-10-06', value: 3 }];
    const den = [{ day: '2026-10-05', value: 1 }, { day: '2026-10-06', value: 9 }];
    const ratios = [{ day: '2026-10-05', value: 1 }, { day: '2026-10-06', value: 3 / 9 }];
    const [week] = rollUp(ratios, 'day', 'week', 'ratio', { num, den });
    expect(week.value).toBeCloseTo(0.4); // 4 over 10, where the mean of 1 and 0.33 would be 0.67
    const [empty] = rollUp(ratios, 'day', 'week', 'ratio', { num, den: den.map((d) => ({ ...d, value: 0 })) });
    expect(empty.value).toBeNull();
  });

  it('turns weekly points into months by the week-ending date, and the month in progress is a part', () => {
    const weekly = Array.from({ length: 5 }, (_, i) => ({ day: addDays('2026-10-04', i * 7), value: 1 })); // 4, 11, 18, 25 Oct and 1 Nov
    const months = rollUp(weekly, 'week', 'month', 'sum');
    expect(months).toEqual([
      { day: '2026-10-31', value: 4 },
      { day: '2026-11-30', value: 1, partial: true },
    ]);
  });

  it('returns the points unchanged at their own grain, and never refines a coarser series', () => {
    expect(rollUp(run, 'day', 'day', 'sum')).toBe(run);
    expect(rollUp(run, 'week', 'day', 'sum')).toBe(run);
  });
});
