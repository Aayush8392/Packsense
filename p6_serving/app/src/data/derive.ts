import { addDays } from '../format';
import jobs from './jobs.json';
import type { ChangeRow, HealthRow } from './siteData';

export interface Job {
  name: string;
  cadence: 'daily' | 'weekly' | 'monthly';
  /** The time of day (UTC) a daily job starts, where the page says it. */
  at?: string;
}

export const JOBS: Job[] = jobs as Job[];

/** Products edited on a day: the "any" row of the change file (a product counts once however many kinds of edit it had). null when hidden or absent. */
export function editsOnDay(rows: ChangeRow[], day: string, scope = 'all'): number | null {
  const matching = rows.filter((row) => row.day === day && row.scope === scope && row.group === 'any');
  if (matching.length === 0) return null;
  if (matching.some((row) => row.products === null)) return null;
  return matching.reduce((sum, row) => sum + (row.products ?? 0), 0);
}

export interface RightNow {
  /** When Open Food Facts published its newest file, and when our copy received it. */
  offFilePublished: Date | null;
  ourCopyReceived: Date | null;
}

function newestValue(rows: HealthRow[], subject: string, metric: string): number | null {
  const matching = rows.filter((row) => row.subject === subject && row.metric === metric && row.value !== null);
  if (matching.length === 0) return null;
  matching.sort((a, b) => (a.day < b.day ? 1 : -1));
  return matching[0].value;
}

export function rightNow(rows: HealthRow[]): RightNow {
  const seconds = (metric: string) => {
    const value = newestValue(rows, 'pipeline', metric);
    return value === null ? null : new Date(value * 1000);
  };
  return { offFilePublished: seconds('off_newest_file_published'), ourCopyReceived: seconds('our_capture_landed') };
}

export interface DailyJobsVerdict {
  /** The day that was checked: the newest COMPLETE day in the table (the newest day in it is still in progress). */
  day: string;
  expected: number;
  /** Daily jobs with no run that day, and daily jobs with a run that did not succeed. */
  missing: string[];
  failed: string[];
}

/** Did every daily job run on the newest complete day? null when the table is too short to say. */
export function dailyJobsVerdict(rows: HealthRow[]): DailyJobsVerdict | null {
  const jobRows = rows.filter((row) => JOBS.some((job) => job.name === row.subject));
  if (jobRows.length === 0) return null;
  const days = [...new Set(jobRows.map((row) => row.day))].sort();
  const newest = days[days.length - 1];
  const day = addDays(newest, -1);
  if (!days.includes(day)) return null;
  const daily = JOBS.filter((job) => job.cadence === 'daily');
  const value = (name: string, metric: string) =>
    rows.find((row) => row.day === day && row.subject === name && row.metric === metric)?.value ?? 0;
  return {
    day,
    expected: daily.length,
    missing: daily.filter((job) => value(job.name, 'runs') === 0).map((job) => job.name),
    failed: daily.filter((job) => value(job.name, 'runs') > 0 && value(job.name, 'failed_runs') > 0).map((job) => job.name),
  };
}

/** The next time the daily load starts after `now`, in plain words. */
export function nextUpdateDue(now: Date): string {
  const at = JOBS.find((job) => job.name === 'packsense-bronze-load')?.at ?? '06:45';
  const [hour, minute] = at.split(':').map(Number);
  const todays = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, minute));
  return now < todays ? `today, about ${at} UTC` : `tomorrow, about ${at} UTC`;
}

