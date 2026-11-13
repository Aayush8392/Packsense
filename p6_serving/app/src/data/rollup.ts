import { addDays } from '../format';
import type { DayPoint } from './series';

/** The size of one point on a chart: a day, a week (ending on a Sunday, as the OFF weekly file does) or a calendar month. */
export type Grain = 'day' | 'week' | 'month';

/**
 * How points of a finer grain become one point of a coarser grain:
 *  - sum: events in the period (products edited, flags that ended);
 *  - last: a level at the end of the period (products held, open flags);
 *  - max: the largest value in the period (the longest run of a job);
 *  - ratio: the period's own ratio, the sum of the top parts over the sum of the bottom parts (never an average of daily ratios).
 */
export type Rollup = 'sum' | 'last' | 'max' | 'ratio';

/** The two sums of a ratio, one point per point of the chart. */
export interface Parts {
  num: DayPoint[];
  den: DayPoint[];
}

export const GRAIN_ORDER: Grain[] = ['day', 'week', 'month'];

export const GRAIN_WORDS: Record<Grain, { one: string; many: string; heading: string }> = {
  day: { one: 'day', many: 'days', heading: 'Day' },
  week: { one: 'week', many: 'weeks', heading: 'Week ending' },
  month: { one: 'month', many: 'months', heading: 'Month' },
};

/** A point must have at least this many buckets for a coarser view to be offered. */
export const MIN_BUCKETS = 4;

function weekday(iso: string): number {
  return new Date(`${iso}T00:00:00Z`).getUTCDay();
}

/** The last day of the period that holds `iso`: the same day, the Sunday on or after it, or the last day of its month. */
export function periodEnd(iso: string, grain: Grain): string {
  if (grain === 'day') return iso;
  if (grain === 'week') return addDays(iso, (7 - weekday(iso)) % 7);
  const [year, month] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

/** The first day of the period that ends on `end`. */
export function periodStart(end: string, grain: Grain): string {
  if (grain === 'day') return end;
  if (grain === 'week') return addDays(end, -6);
  return `${end.slice(0, 8)}01`;
}

/** The grains a chart whose points are `native` can show: its own and every coarser one. */
export function grainsFrom(native: Grain): Grain[] {
  return GRAIN_ORDER.slice(GRAIN_ORDER.indexOf(native));
}

function combine(values: (number | null)[], rule: Rollup): number | null {
  // A value that is not known (a count of 1 to 4, hidden on purpose) makes the period not known: a total with a hole in it would be wrong.
  if (values.length === 0 || values.some((v) => v === null)) return null;
  const known = values as number[];
  if (rule === 'last') return known[known.length - 1];
  if (rule === 'max') return Math.max(...known);
  return known.reduce((sum, v) => sum + v, 0);
}

/**
 * Points of grain `native` turned into points of the coarser grain `grain`. The point's `day` is the last day of its period, and a period the
 * data does not cover from its first to its last day is marked `partial`. For a ratio, `parts` holds the two sums, aligned with `points`.
 */
export function rollUp(points: DayPoint[], native: Grain, grain: Grain, rule: Rollup, parts?: Parts): DayPoint[] {
  if (grain === native || GRAIN_ORDER.indexOf(grain) < GRAIN_ORDER.indexOf(native)) return points;
  const step = native === 'day' ? 1 : 7;
  const groups = new Map<string, number[]>();
  points.forEach((p, i) => {
    const key = periodEnd(p.day, grain);
    groups.set(key, [...(groups.get(key) ?? []), i]);
  });
  return [...groups.entries()].map(([end, indexes]) => {
    const first = points[indexes[0]].day;
    const last = points[indexes[indexes.length - 1]].day;
    const partial = !(addDays(first, -step) < periodStart(end, grain) && addDays(last, step) > end);
    let value: number | null;
    if (rule === 'ratio') {
      const top = combine(indexes.map((i) => parts?.num[i]?.value ?? null), 'sum');
      const bottom = combine(indexes.map((i) => parts?.den[i]?.value ?? null), 'sum');
      value = top === null || bottom === null || bottom === 0 ? null : top / bottom;
    } else {
      value = combine(indexes.map((i) => points[i].value), rule);
    }
    return partial ? { day: end, value, partial } : { day: end, value };
  });
}
