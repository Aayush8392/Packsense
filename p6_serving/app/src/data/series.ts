import { addDays } from '../format';
import type { Parts } from './rollup';
import type { ChangeRow, QualityRow } from './siteData';

export type Scope = 'all' | 'india';

export interface DayPoint {
  day: string;
  /** null where the value is not known (a count of 1 to 4 that was hidden on purpose). */
  value: number | null;
  /** Set on a period of a coarser view that the data does not cover from its first to its last day (the newest week or month so far). */
  partial?: boolean;
}

/** The eight kinds of edit, in the order the page text lists them, with the plain name shown on the page. */
export const KINDS: { group: string; label: string }[] = [
  { group: 'name_brand', label: 'Name and brand' },
  { group: 'quantity', label: 'Pack size' },
  { group: 'nutrition', label: 'Nutrition' },
  { group: 'nutriscore_nova', label: 'Nutri-Score and NOVA' },
  { group: 'ingredients', label: 'Ingredients' },
  { group: 'allergens', label: 'Allergens' },
  { group: 'categories_labels', label: 'Categories and labels' },
  { group: 'other_tags', label: 'Other tags' },
];

export const SEVERITIES: { id: string; label: string }[] = [
  { id: 'error', label: 'Errors' },
  { id: 'warning', label: 'Warnings' },
  { id: 'info', label: 'Information' },
];

/** Every calendar day from the first to the last, as ISO text. */
export function dayRange(first: string, last: string): string[] {
  const days: string[] = [];
  for (let day = first; day <= last; day = addDays(day, 1)) days.push(day);
  return days;
}

export function qualityDays(rows: QualityRow[], scope: Scope): string[] {
  const days = [...new Set(rows.filter((r) => r.scope === scope).map((r) => r.day))].sort();
  return days.length === 0 ? [] : dayRange(days[0], days[days.length - 1]);
}

/** Products held each day. */
export function productsHeld(rows: QualityRow[], scope: Scope): DayPoint[] {
  const held = new Map<string, number>();
  for (const row of rows) if (row.scope === scope) held.set(row.day, row.productsHeld);
  return qualityDays(rows, scope).map((day) => ({ day, value: held.get(day) ?? null }));
}

/**
 * Open flags per product held, per day. A severity of 'all' adds every severity. Flags with a hidden count (1 to 4) are left out of the sum,
 * so a value is "at least"; the page says so.
 */
export function flagsPerProduct(rows: QualityRow[], scope: Scope, severity: string | 'all'): DayPoint[] {
  const flags = new Map<string, number>();
  const held = new Map<string, number>();
  for (const row of rows) {
    if (row.scope !== scope) continue;
    held.set(row.day, row.productsHeld);
    if (severity === 'all' || row.severity === severity) flags.set(row.day, (flags.get(row.day) ?? 0) + (row.openFlags ?? 0));
  }
  return qualityDays(rows, scope).map((day) => {
    const products = held.get(day);
    return { day, value: products ? (flags.get(day) ?? 0) / products : null };
  });
}

/** The two sums behind `flagsPerProduct` (open flags, products held), so a week or a month can be worked out from them and not from daily ratios. */
export function flagsPerProductParts(rows: QualityRow[], scope: Scope, severity: string | 'all'): Parts {
  const flags = new Map<string, number>();
  const held = new Map<string, number>();
  for (const row of rows) {
    if (row.scope !== scope) continue;
    held.set(row.day, row.productsHeld);
    if (severity === 'all' || row.severity === severity) flags.set(row.day, (flags.get(row.day) ?? 0) + (row.openFlags ?? 0));
  }
  const days = qualityDays(rows, scope);
  return {
    num: days.map((day) => ({ day, value: held.get(day) ? (flags.get(day) ?? 0) : null })),
    den: days.map((day) => ({ day, value: held.get(day) ?? null })),
  };
}

export interface FlagWaterfall {
  first: string;
  last: string;
  start: number;
  /** Flags on products that arrived already flagged, summed over the days after the first. */
  carriedIn: number;
  /** Flags that appeared on products already held. */
  opened: number;
  /** Flags that ended (fixed, or the product left). */
  vanished: number;
  end: number;
  /** What the three flows above miss: counts of 1 to 4 are blanked on purpose, so this is small; it makes the totals add up exactly. */
  rest: number;
}

/**
 * How the open flags changed from the first day to the last: the flags open on the first day, plus those that came with new products, plus those
 * that opened on held products, minus those that ended, plus what is not itemised, equals the flags open on the last day. A blanked count counts as zero.
 */
export function flagWaterfall(rows: QualityRow[], scope: Scope): FlagWaterfall | null {
  const days = qualityDays(rows, scope);
  if (days.length < 2) return null;
  const first = days[0];
  const last = days[days.length - 1];
  let start = 0;
  let end = 0;
  let carriedIn = 0;
  let opened = 0;
  let vanished = 0;
  for (const row of rows) {
    if (row.scope !== scope) continue;
    if (row.day === first) start += row.openFlags ?? 0;
    if (row.day === last) end += row.openFlags ?? 0;
    if (row.day !== first) {
      carriedIn += row.carriedIn ?? 0;
      opened += row.appeared ?? 0;
      vanished += row.ended ?? 0;
    }
  }
  return { first, last, start, carriedIn, opened, vanished, end, rest: end - (start + carriedIn + opened - vanished) };
}

export interface FamilyRow {
  family: string;
  /** The severities this kind of flag has on the day, in order error, warning, information. */
  severities: string[];
  flags: number;
  /** Share of all open flags that day, 0 to 1. */
  share: number;
}

/** The kinds of flag with the most open flags on a day. */
export function topFamilies(rows: QualityRow[], scope: Scope, day: string, limit: number): FamilyRow[] {
  const byFamily = new Map<string, { flags: number; severities: Set<string> }>();
  let total = 0;
  for (const row of rows) {
    if (row.scope !== scope || row.day !== day) continue;
    const entry = byFamily.get(row.family) ?? { flags: 0, severities: new Set<string>() };
    entry.flags += row.openFlags ?? 0;
    entry.severities.add(row.severity);
    byFamily.set(row.family, entry);
    total += row.openFlags ?? 0;
  }
  const order = SEVERITIES.map((s) => s.id);
  return [...byFamily.entries()]
    .map(([family, e]) => ({
      family,
      severities: [...e.severities].sort((a, b) => order.indexOf(a) - order.indexOf(b)),
      flags: e.flags,
      share: total === 0 ? 0 : e.flags / total,
    }))
    .sort((a, b) => b.flags - a.flags || a.family.localeCompare(b.family))
    .slice(0, limit);
}

/** The days the change file covers, as a continuous range. */
export function changeDays(rows: ChangeRow[], scope: Scope): string[] {
  const days = [...new Set(rows.filter((r) => r.scope === scope).map((r) => r.day))].sort();
  return days.length === 0 ? [] : dayRange(days[0], days[days.length - 1]);
}

function changeValue(rows: ChangeRow[], scope: Scope, day: string, group: string): number | null {
  const matching = rows.filter((r) => r.scope === scope && r.day === day && r.group === group);
  if (matching.length === 0) return 0; // the file holds a row only for a day with at least one such edit
  if (matching.some((r) => r.products === null)) return null; // 1 to 4, hidden on purpose
  return matching.reduce((sum, r) => sum + (r.products ?? 0), 0);
}

/** Products edited (a product counts once however many kinds of edit it had), or new products, per day. */
export function changeSeries(rows: ChangeRow[], scope: Scope, group: 'any' | 'new_product' | string, days?: string[]): DayPoint[] {
  return (days ?? changeDays(rows, scope)).map((day) => ({ day, value: changeValue(rows, scope, day, group) }));
}

export interface KindRow {
  group: string;
  label: string;
  products: number | null;
}

/** Products edited by each kind of edit on one day. The kinds overlap, so these are never added together. */
export function kindsOnDay(rows: ChangeRow[], scope: Scope, day: string): KindRow[] {
  return KINDS.map(({ group, label }) => ({ group, label, products: changeValue(rows, scope, day, group) }));
}
