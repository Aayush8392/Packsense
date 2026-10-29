import { addDays } from '../format';
import type { ChangeRow, QualityRow } from './siteData';

export type Scope = 'all' | 'india';

export interface DayPoint {
  day: string;
  /** null where the value is not known (a count of 1 to 4 that was hidden on purpose). */
  value: number | null;
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
