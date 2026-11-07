import { OFF_OTHER_KIND, type OffOpenFlagRow, type OffWeeklyRow } from './siteData';
import type { DayPoint } from './series';

/** A column of the weekly file as points (the week's end date is the "day"); a hidden count (1 to 4) is a gap. */
export function weeklyPoints(rows: OffWeeklyRow[], pick: (row: OffWeeklyRow) => number | null): DayPoint[] {
  return [...rows].sort((a, b) => a.weekEnd.localeCompare(b.weekEnd)).map((row) => ({ day: row.weekEnd, value: pick(row) }));
}

export type FlagSeverityChoice = 'all' | 'error';

/** Flags that ended, or appeared, each week: every severity added up, or errors only. A hidden count adds nothing, so a total is "at least". */
export function flagMoves(rows: OffWeeklyRow[], event: 'ended' | 'appeared', severity: FlagSeverityChoice): DayPoint[] {
  return weeklyPoints(rows, (r) => {
    const parts = event === 'ended' ? [r.endedError, r.endedWarning, r.endedInfo] : [r.appearedError, r.appearedWarning, r.appearedInfo];
    return severity === 'error' ? parts[0] : parts.reduce<number>((sum, v) => sum + (v ?? 0), 0);
  });
}

/** Open flags over the whole of OFF at each snapshot for one severity (every kind added up; a hidden count adds nothing). */
export function openBySeverity(rows: OffOpenFlagRow[], severity: string): DayPoint[] {
  const byDay = new Map<string, number>();
  for (const row of rows) if (row.severity === severity) byDay.set(row.day, (byDay.get(row.day) ?? 0) + (row.openFlags ?? 0));
  return [...byDay.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, value]) => ({ day, value }));
}

export interface OpenKind {
  severity: string;
  kind: string;
  now: number;
  /** The same kind at the oldest snapshot, or 0 when it had no open flags then. */
  first: number;
}

/** The kinds of flag with the most open flags at the newest snapshot, with their count at the oldest one. The row that adds up the small kinds is not a kind. */
export function topOpenKinds(rows: OffOpenFlagRow[], limit: number): { newest: string; oldest: string; kinds: OpenKind[] } | null {
  const days = [...new Set(rows.map((r) => r.day))].sort();
  if (days.length < 2) return null;
  const newest = days[days.length - 1];
  const oldest = days[0];
  const at = (day: string) => new Map(rows.filter((r) => r.day === day && r.kind !== OFF_OTHER_KIND && r.openFlags !== null).map((r) => [`${r.severity}|${r.kind}`, r.openFlags as number]));
  const now = at(newest);
  const first = at(oldest);
  const kinds = [...now.entries()]
    .map(([key, count]) => {
      const [severity, kind] = key.split('|');
      return { severity, kind, now: count, first: first.get(key) ?? 0 };
    })
    .sort((a, b) => b.now - a.now || a.kind.localeCompare(b.kind))
    .slice(0, limit);
  return { newest, oldest, kinds };
}
