import type { LineSeries } from '../charts/LineChart';
import { ITEMS } from '../data/brands';
import { flagName } from '../data/flagNames';
import { KINDS, changeDays, changeSeries, dayRange, qualityDays, type DayPoint, type Scope } from '../data/series';
import type { BrandRow, ChangeRow, QualityRow } from '../data/siteData';
import { formatCount, formatDay } from '../format';

/**
 * The chart gallery: every chart is a fixed template filled with numbers from the four published files, and every caption is written by code from
 * those same numbers. Nothing here calls a model. A count of 1 to 4 is blanked in the files (null here) and is left out of a sum, so a total is
 * "at least"; each chart's note says so where it matters.
 */

/** Days a time chart looks back. */
export const WINDOW_DAYS = 30;

export interface BarRow {
  id: string;
  label: string;
  /** null when the value is not known (hidden on purpose). */
  value: number | null;
  /** The value as it is written beside the bar and in the table. */
  display: string;
  /** A small line under the label (for a flag kind, its Open Food Facts tag). */
  small?: string;
}

interface ChartBase {
  id: string;
  title: string;
  /** One sentence saying what is drawn and what is left out. */
  note: string;
  /** One sentence by code from the numbers: what the latest figures say. */
  caption: string;
}

export interface LineChartSpec extends ChartBase {
  kind: 'line';
  series: LineSeries[];
  format: (value: number) => string;
}

export interface BarChartSpec extends ChartBase {
  kind: 'bars';
  rows: BarRow[];
  /** The heading of the value column in the table. */
  valueHeading: string;
}

export type GalleryChart = LineChartSpec | BarChartSpec;

export interface GalleryData {
  quality: QualityRow[];
  change: ChangeRow[];
  brands: BrandRow[];
}

/** A share from 0 to 1 as a percent: a decimal below 10%, whole numbers above. */
export function percent(share: number): string {
  const value = share * 100;
  if (value === 0) return '0%';
  return value < 10 ? `${value.toFixed(1)}%` : `${Math.round(value)}%`;
}

/** The newest `count` days of a day list. */
function trailing<T>(items: T[], count: number): T[] {
  return items.slice(Math.max(0, items.length - count));
}

function sumKnown(points: DayPoint[]): number {
  return points.reduce((sum, p) => sum + (p.value ?? 0), 0);
}

export interface WeekOverWeek {
  recent: number;
  before: number;
}

/** The newest 7 days against the 7 before them; null when there are fewer than 14 days. */
export function weekOverWeek(points: DayPoint[]): WeekOverWeek | null {
  if (points.length < 14) return null;
  const recent = sumKnown(points.slice(-7));
  const before = sumKnown(points.slice(-14, -7));
  return { recent, before };
}

/** "up 12%", "down 4%", "about the same" or "up from none" against the week before. A change under 1% counts as the same. */
export function changeWords(recent: number, before: number): string {
  if (before === 0) return recent === 0 ? 'about the same' : 'up from none';
  const change = (recent - before) / before;
  if (Math.abs(change) < 0.01) return 'about the same';
  return `${change > 0 ? 'up' : 'down'} ${Math.round(Math.abs(change) * 100)}%`;
}

/** Flags that appeared on known products and flags that ended, per day: every severity and kind added up. */
function flagFlow(quality: QualityRow[], scope: Scope): LineChartSpec | null {
  const all = qualityDays(quality, scope);
  if (all.length === 0) return null;
  const days = trailing(all, WINDOW_DAYS);
  const sums = (pick: (r: QualityRow) => number | null): DayPoint[] => {
    const byDay = new Map<string, number>();
    for (const row of quality) if (row.scope === scope) byDay.set(row.day, (byDay.get(row.day) ?? 0) + (pick(row) ?? 0));
    return days.map((day) => ({ day, value: byDay.get(day) ?? null }));
  };
  const appeared = sums((r) => r.appeared);
  const ended = sums((r) => r.ended);
  const a = weekOverWeek(appeared);
  const e = weekOverWeek(ended);
  const caption =
    a && e
      ? `In the last 7 days at least ${formatCount(a.recent)} flags appeared on products we already held (${changeWords(a.recent, a.before)} on the 7 days before) and at least ${formatCount(e.recent)} ended (${changeWords(e.recent, e.before)}).`
      : 'There are not yet two full weeks of days to compare.';
  return {
    kind: 'line',
    id: 'flag-flow',
    title: 'Flags that appeared and flags that ended',
    note: `Each day, flags that appeared on a product we already held and flags that ended. A flag that ended was fixed or its product left; the file does not say which. Counts of 1 to 4 are left out, so each day is "at least". The last ${days.length} days.`,
    caption,
    series: [
      { id: 'appeared', label: 'Appeared on known products', points: appeared, marker: 'circle', color: 'var(--primary)' },
      { id: 'ended', label: 'Ended', points: ended, marker: 'triangle', dash: '6 4', color: 'var(--secondary)' },
    ],
    format: formatCount,
  };
}

/** Open flags of each kind on one day (every severity added); null when any row of the kind was blanked. */
function openByFamily(quality: QualityRow[], scope: Scope, day: string): Map<string, number | null> {
  const byFamily = new Map<string, number | null>();
  for (const row of quality) {
    if (row.scope !== scope || row.day !== day) continue;
    const before = byFamily.get(row.family);
    if (before === null || row.openFlags === null) byFamily.set(row.family, null);
    else byFamily.set(row.family, (before ?? 0) + row.openFlags);
  }
  return byFamily;
}

const signed = (value: number) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${formatCount(Math.abs(value))}`;

/** The kinds of flag whose number of open flags moved most between the newest day and 30 days before (or the first day we have). */
function familyChange(quality: QualityRow[], scope: Scope): BarChartSpec | null {
  const days = qualityDays(quality, scope);
  if (days.length < 2) return null;
  const last = days[days.length - 1];
  const first = days[Math.max(0, days.length - 1 - WINDOW_DAYS)];
  const now = openByFamily(quality, scope, last);
  const then = openByFamily(quality, scope, first);
  const moves: { family: string; from: number; to: number }[] = [];
  for (const [family, to] of now) {
    const from = then.get(family) ?? (then.has(family) ? null : 0);
    if (to === null || from === null) continue; // a blanked end hides the move
    moves.push({ family, from, to });
  }
  const top = moves.sort((x, y) => Math.abs(y.to - y.from) - Math.abs(x.to - x.from) || x.family.localeCompare(y.family)).slice(0, 8);
  if (top.length === 0) return null;
  const span = dayRange(first, last).length - 1;
  const lead = top[0];
  const verb = lead.to >= lead.from ? 'rose' : 'fell';
  return {
    kind: 'bars',
    id: 'family-change',
    title: 'Kinds of flag that changed most',
    note: `The change in open flags of each kind between ${formatDay(first)} and ${formatDay(last)} (${span} days), the eight biggest moves. A kind with a hidden count at either end is left out.`,
    caption: `${flagName(lead.family).name} ${verb} most: from ${formatCount(lead.from)} open flags to ${formatCount(lead.to)} over ${span} days.`,
    valueHeading: `Change in open flags, ${span} days`,
    rows: top.map((m) => ({
      id: m.family,
      label: flagName(m.family).name,
      value: m.to - m.from,
      display: `${signed(m.to - m.from)} (${formatCount(m.from)} to ${formatCount(m.to)})`,
      small: m.family === 'unmapped' ? undefined : m.family,
    })),
  };
}

const KIND_MARKERS: LineSeries['marker'][] = ['circle', 'triangle', 'square', 'diamond'];
const KIND_COLORS = ['var(--primary)', 'var(--secondary)', 'var(--primary-mid)', 'var(--accent)'];
const KIND_DASH = [undefined, '6 4', '2 3', '10 3 2 3'];

/** The share of edited products that had each kind of edit, per day, for the four most common kinds. */
function kindShare(change: ChangeRow[], scope: Scope): LineChartSpec | null {
  const all = changeDays(change, scope);
  if (all.length === 0) return null;
  const days = trailing(all, WINDOW_DAYS);
  const edited = changeSeries(change, scope, 'any', days);
  const built = KINDS.map(({ group, label }) => {
    const own = changeSeries(change, scope, group, days);
    const points: DayPoint[] = days.map((day, i) => {
      const total = edited[i].value;
      const part = own[i].value;
      return { day, value: total === null || part === null || total === 0 ? null : part / total };
    });
    const known = points.filter((p) => p.value !== null) as { value: number }[];
    const mean = known.length === 0 ? 0 : known.reduce((sum, p) => sum + p.value, 0) / known.length;
    return { group, label, points, mean };
  })
    .sort((a, b) => b.mean - a.mean)
    .slice(0, 4);
  if (built[0].mean === 0) return null;
  const lead = built[0];
  const next = built[1];
  return {
    kind: 'line',
    id: 'kind-share',
    title: 'What kind of edit products get',
    note: `The share of the day's edited products that had each of the four most common kinds of edit. One product can have several kinds, so the shares add up to more than 100%. The last ${days.length} days.`,
    caption: `${lead.label} is the most common kind: ${percent(lead.mean)} of edited products on an average day, ahead of ${next.label.toLowerCase()} at ${percent(next.mean)}.`,
    series: built.map((b, i) => ({
      id: b.group,
      label: b.label,
      points: b.points,
      marker: KIND_MARKERS[i],
      dash: KIND_DASH[i],
      color: KIND_COLORS[i],
    })),
    format: percent,
  };
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0];

export function weekdayOf(iso: string): number {
  return new Date(`${iso}T00:00:00Z`).getUTCDay();
}

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

const HALF_WINDOW = 3;

const signedPercent = (ratio: number) => {
  const value = Math.round((ratio - 1) * 100);
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value)}%`;
};

/**
 * How much busier or quieter each day of the week is than an ordinary day. Each day is compared with the MEDIAN of the 7 days around it (3 on
 * each side), so a steady rise over the month and one huge day (a day after a missed capture catches up) do not tilt the weekdays; then each
 * weekday takes the median of its own comparisons. A day needs all 7 of its window to be known.
 */
function weekdayEdits(change: ChangeRow[], scope: Scope): BarChartSpec | null {
  const days = changeDays(change, scope);
  const edited = changeSeries(change, scope, 'any', days);
  const ratios: number[][] = Array.from({ length: 7 }, () => []);
  for (let i = HALF_WINDOW; i < days.length - HALF_WINDOW; i++) {
    const window = edited.slice(i - HALF_WINDOW, i + HALF_WINDOW + 1).map((p) => p.value);
    if (window.some((v) => v === null)) continue;
    const base = median(window as number[]);
    if (base === 0) continue;
    ratios[weekdayOf(days[i])].push((edited[i].value as number) / base);
  }
  if (WEEK_ORDER.some((d) => ratios[d].length === 0)) return null;
  const rows = WEEK_ORDER.map((d) => ({ weekday: d, ratio: median(ratios[d]), days: ratios[d].length }));
  const busiest = rows.reduce((best, m) => (m.ratio > best.ratio ? m : best));
  const quietest = rows.reduce((best, m) => (m.ratio < best.ratio ? m : best));
  return {
    kind: 'bars',
    id: 'weekday-edits',
    title: 'Edits by day of the week',
    note: `How much busier or quieter each day of the week is than an ordinary day, over the ${days.length} whole days we have (new products count too). Each day is compared with the median of the 7 days around it, so one huge day or a steady rise does not tilt the result; the bar is the middle of that weekday's comparisons, from only a few days each.`,
    caption: `In this period ${WEEKDAYS[busiest.weekday]} was the busiest day, ${signedPercent(busiest.ratio)} on an ordinary day, and ${WEEKDAYS[quietest.weekday]} the quietest, ${signedPercent(quietest.ratio)}.`,
    valueHeading: 'Against an ordinary day',
    rows: rows.map((m) => ({
      id: WEEKDAYS[m.weekday],
      label: WEEKDAYS[m.weekday],
      value: (m.ratio - 1) * 100,
      display: signedPercent(m.ratio),
      small: `${m.days} ${m.days === 1 ? 'day' : 'days'} compared`,
    })),
  };
}

/** India's share of all products edited, per day. Not market-specific: it compares the two markets. */
function indiaShare(change: ChangeRow[]): LineChartSpec | null {
  const allDays = changeDays(change, 'all');
  const indiaDays = new Set(changeDays(change, 'india'));
  if (allDays.length === 0 || indiaDays.size === 0) return null;
  const days = trailing(allDays, WINDOW_DAYS);
  const world = changeSeries(change, 'all', 'any', days);
  const india = changeSeries(change, 'india', 'any', days);
  const points: DayPoint[] = days.map((day, i) => {
    const total = world[i].value;
    const part = india[i].value;
    return { day, value: total === null || part === null || total === 0 ? null : part / total };
  });
  const windowShare = (a: number, b: number) => {
    const t = sumKnown(world.slice(a, b));
    const p = sumKnown(india.slice(a, b));
    return t === 0 ? null : p / t;
  };
  const recent = days.length >= 14 ? windowShare(days.length - 7, days.length) : null;
  const before = days.length >= 14 ? windowShare(days.length - 14, days.length - 7) : null;
  const caption =
    recent !== null && before !== null
      ? `India made up ${percent(recent)} of the products edited in the last 7 days, against ${percent(before)} in the 7 days before.`
      : 'There are not yet two full weeks of days to compare.';
  return {
    kind: 'line',
    id: 'india-share',
    title: "India's share of all edits",
    note: `The share of all products edited each day (new products count too) that are Indian products. Days with a hidden count are left out. The last ${days.length} days.`,
    caption,
    series: [{ id: 'india', label: "India's share of edits", points, marker: 'circle', color: 'var(--primary)' }],
    format: percent,
  };
}

/** The share of products that leave each of the seven things empty, over the ranked brands of a market (brands with at least 30 products). */
function emptyFields(brands: BrandRow[], scope: Scope): BarChartSpec | null {
  const own = brands.filter((b) => b.scope === scope);
  const total = own.reduce((sum, b) => sum + b.products, 0);
  if (total === 0) return null;
  const rows = ITEMS.map(({ key, label }) => {
    const filled = own.reduce((sum, b) => sum + b.filled[key], 0);
    return { key, label, empty: 1 - filled / total };
  }).sort((a, b) => b.empty - a.empty);
  const most = rows[0];
  const least = rows[rows.length - 1];
  return {
    kind: 'bars',
    id: 'empty-fields',
    title: 'Fields brands leave empty most often',
    note: `The share of products with each of the seven things missing, over the ${formatCount(own.length)} named brands with at least 30 products (${formatCount(total)} products). Smaller brands are not in the file.`,
    caption: `Missing most often: ${most.label}, on ${percent(most.empty)} of these products. Missing least often: ${least.label}, on ${percent(least.empty)}.`,
    valueHeading: 'Products with it missing',
    rows: rows.map((r) => ({ id: r.key, label: r.label, value: r.empty * 100, display: percent(r.empty) })),
  };
}

const BANDS: { id: string; label: string; from: number; to: number }[] = [
  { id: '30-49', label: '30 to 49 products', from: 30, to: 49 },
  { id: '50-99', label: '50 to 99 products', from: 50, to: 99 },
  { id: '100-299', label: '100 to 299 products', from: 100, to: 299 },
  { id: '300-999', label: '300 to 999 products', from: 300, to: 999 },
  { id: '1000', label: '1,000 or more products', from: 1000, to: Infinity },
];

/** How many of the seven things a brand's products fill on average, by the size of the brand. */
function sizeBands(brands: BrandRow[], scope: Scope): BarChartSpec | null {
  const own = brands.filter((b) => b.scope === scope);
  const rows = BANDS.map((band) => {
    const inBand = own.filter((b) => b.products >= band.from && b.products <= band.to);
    const products = inBand.reduce((sum, b) => sum + b.products, 0);
    const points = inBand.reduce((sum, b) => sum + b.points, 0);
    return { band, brands: inBand.length, score: products === 0 ? null : points / products };
  }).filter((r) => r.score !== null);
  if (rows.length < 2) return null;
  const small = rows[0];
  const large = rows[rows.length - 1];
  const higher = (large.score as number) >= (small.score as number);
  return {
    kind: 'bars',
    id: 'size-bands',
    title: 'Brand size and completeness',
    note: 'How many of the seven things the products of a brand fill on average (out of 7), by how many products the brand has. Brands with at least 30 products only; each product counts once.',
    caption: `Brands with ${large.band.label.replace(' products', '').toLowerCase()} products fill ${(large.score as number).toFixed(1)} of the seven things on average, ${higher ? 'against' : 'below'} ${(small.score as number).toFixed(1)} for brands with ${small.band.label.replace(' products', '')} products.`,
    valueHeading: 'Things filled on average, out of 7',
    rows: rows.map((r) => ({
      id: r.band.id,
      label: r.band.label,
      value: r.score,
      display: `${(r.score as number).toFixed(1)} of 7`,
      small: `${formatCount(r.brands)} ${r.brands === 1 ? 'brand' : 'brands'}`,
    })),
  };
}

/**
 * Every chart of the gallery for one market, in a fixed order. A chart whose figures are missing or too few to draw is left out (never drawn
 * from a guess). India's share is a comparison of the two markets, so it is the same for either choice.
 */
export function buildGallery(data: GalleryData, scope: Scope): GalleryChart[] {
  const charts = [
    flagFlow(data.quality, scope),
    familyChange(data.quality, scope),
    kindShare(data.change, scope),
    weekdayEdits(data.change, scope),
    indiaShare(data.change),
    emptyFields(data.brands, scope),
    sizeBands(data.brands, scope),
  ];
  return charts.filter((c): c is GalleryChart => c !== null);
}

/** The IST calendar day number (days since 1 Jan 1970 on the India clock). */
export function dayNumber(moment: Date): number {
  return Math.floor((moment.getTime() + 330 * 60_000) / 86_400_000);
}

/** The chart the carousel opens on: a fixed rotation by day number, so a visitor sees a different chart each day and every chart in turn. */
export function startIndex(moment: Date, count: number): number {
  return count <= 0 ? 0 : dayNumber(moment) % count;
}
