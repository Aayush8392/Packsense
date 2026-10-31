import { JOBS, type Job } from './derive';
import { dayRange, type DayPoint } from './series';
import type { HealthRow } from './siteData';

const DAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
const DAY_NAMES: Record<string, string> = { MON: 'Mondays', TUE: 'Tuesdays', WED: 'Wednesdays', THU: 'Thursdays', FRI: 'Fridays', SAT: 'Saturdays', SUN: 'Sundays' };

function ordinal(n: number): string {
  const rest = n % 100;
  if (rest >= 11 && rest <= 13) return `${n}th`;
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`;
}

/** A Quartz cron (seconds, minutes, hours, day of month, month, day of week) in plain words: "Every day, 06:45 UTC", "Mondays, 12:00 UTC", "The 3rd of each month, 10:30 UTC". */
export function describeCron(cron: string): string {
  const [, minute, hour, dayOfMonth, , dayOfWeek] = cron.trim().split(/\s+/);
  const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')} UTC`;
  if (DAYS.includes(dayOfWeek)) return `${DAY_NAMES[dayOfWeek]}, ${time}`;
  if (/^\d+$/.test(dayOfMonth)) return `The ${ordinal(Number(dayOfMonth))} of each month, ${time}`;
  return `Every day, ${time}`;
}

export type VerdictId = 'on-time' | 'late' | 'missed' | 'unknown';

export const VERDICTS: Record<VerdictId, { label: string; glyph: string; meaning: string }> = {
  'on-time': { label: 'On time', glyph: '✓', meaning: 'It succeeded within its usual rhythm.' },
  late: { label: 'Late', glyph: '!', meaning: 'Its last success is older than its rhythm allows, so one slot may have been missed.' },
  missed: { label: 'Missed', glyph: '✕', meaning: 'Its last success is much older than its rhythm allows, or there is none in the last 30 days.' },
  unknown: { label: 'Not known', glyph: '?', meaning: 'This board looks back 30 days, which is shorter than the gap between runs of this job.' },
};

/** Hours since the last success at which a job is called late and then missed: one period, and about a quarter more (then about a half more). */
export const LIMITS: Record<Job['cadence'], { late: number; missed: number }> = {
  daily: { late: 30, missed: 54 },
  weekly: { late: 8 * 24, missed: 10 * 24 },
  monthly: { late: 33 * 24, missed: 40 * 24 },
};

/** Judges a job against its own rhythm. `hours` is null when the board holds no success in its 30-day window. */
export function verdictFor(cadence: Job['cadence'], hours: number | null): VerdictId {
  if (hours === null) return cadence === 'monthly' ? 'unknown' : 'missed';
  const limit = LIMITS[cadence];
  if (hours <= limit.late) return 'on-time';
  return hours <= limit.missed ? 'late' : 'missed';
}

export interface JobStatus {
  job: Job;
  when: string;
  hours: number | null;
  verdict: VerdictId;
  /** Runs, and runs that did not succeed, on the days of the last 14 in the table. */
  runs: number;
  notSucceeded: number;
  /** The longest single run in those days, in seconds; null when none was recorded. */
  longestSeconds: number | null;
}

const WINDOW_DAYS = 14;

/** The newest day with a "hours since last success" row: the day of the newest daily check. */
export function checkDay(rows: HealthRow[]): string | null {
  const days = rows.filter((row) => row.metric === 'hours_since_last_success').map((row) => row.day).sort();
  return days.length === 0 ? null : days[days.length - 1];
}

export function jobStatuses(rows: HealthRow[]): JobStatus[] {
  const day = checkDay(rows);
  if (day === null) return [];
  const since = new Date(`${day}T00:00:00Z`);
  since.setUTCDate(since.getUTCDate() - (WINDOW_DAYS - 1));
  const from = since.toISOString().slice(0, 10);
  return JOBS.map((job) => {
    const own = rows.filter((row) => row.subject === job.name);
    const hours = own.find((row) => row.day === day && row.metric === 'hours_since_last_success')?.value ?? null;
    const recent = own.filter((row) => row.day >= from && row.day <= day);
    const sum = (metric: string) => recent.filter((row) => row.metric === metric).reduce((total, row) => total + (row.value ?? 0), 0);
    const durations = recent.filter((row) => row.metric === 'max_duration_seconds' && row.value !== null).map((row) => row.value as number);
    return {
      job,
      when: describeCron(job.cron),
      hours,
      verdict: verdictFor(job.cadence, hours),
      runs: sum('runs'),
      notSucceeded: sum('failed_runs'),
      longestSeconds: durations.length === 0 ? null : Math.max(...durations),
    };
  });
}

export function verdictCounts(statuses: JobStatus[]): Record<VerdictId, number> {
  const counts: Record<VerdictId, number> = { 'on-time': 0, late: 0, missed: 0, unknown: 0 };
  for (const status of statuses) counts[status.verdict] += 1;
  return counts;
}

/** "17 hours", "2.4 days": how long ago, in the unit that reads best. */
export function formatAge(hours: number): string {
  if (hours < 48) return `${Number(hours.toFixed(1))} hours`;
  return `${Number((hours / 24).toFixed(1))} days`;
}

/** "78 seconds", "4.2 minutes". */
export function formatDuration(seconds: number): string {
  if (seconds < 120) return `${Math.round(seconds)} seconds`;
  return `${Number((seconds / 60).toFixed(1))} minutes`;
}

export interface RunSeries {
  name: string;
  points: DayPoint[];
}

export const CHART_JOBS = 5;

/**
 * The longest run of each daily job per day, in minutes, for the five daily jobs whose runs were longest (twelve lines would not read, and a weekly job that runs
 * for hours would flatten the rest; the table beside shows every job). Days with no run are gaps, not zeros.
 */
export function runtimeSeries(rows: HealthRow[]): RunSeries[] {
  const daily = JOBS.filter((job) => job.cadence === 'daily');
  const own = rows.filter((row) => row.metric === 'max_duration_seconds' && row.value !== null && daily.some((job) => job.name === row.subject));
  if (own.length === 0) return [];
  const days = [...new Set(own.map((row) => row.day))].sort();
  const range = dayRange(days[0], days[days.length - 1]);
  const longest = (name: string) => Math.max(...own.filter((row) => row.subject === name).map((row) => row.value as number));
  return daily
    .filter((job) => own.some((row) => row.subject === job.name))
    .sort((a, b) => longest(b.name) - longest(a.name) || a.name.localeCompare(b.name))
    .slice(0, CHART_JOBS)
    .map((job) => ({
      name: job.name,
      points: range.map((day) => {
        const row = own.find((r) => r.subject === job.name && r.day === day);
        return { day, value: row ? (row.value as number) / 60 : null };
      }),
    }));
}

/** What each outside service is for, in plain words. Matched on the start of the name the collector writes (the name carries its own short note in brackets). */
export const SERVICE_PURPOSES: { startsWith: string; purpose: string }[] = [
  { startsWith: 'Backblaze', purpose: 'Online storage where a safe copy of each daily file is kept and read back.' },
  { startsWith: 'Hugging Face', purpose: "Where Open Food Facts' full weekly copies are published; the weekly job reads them." },
  { startsWith: 'OFF delta index', purpose: "The list of Open Food Facts' daily files, checked every morning to find the newest one." },
  { startsWith: 'OFF product API', purpose: "Open Food Facts' lookup service for single products, used to check whether a missing product was really removed." },
  { startsWith: 'OFF taxonomy', purpose: "Open Food Facts' official names for categories, labels and flags, used to name things on this site." },
  { startsWith: 'PyPI', purpose: 'The download site for the software libraries the jobs use.' },
  { startsWith: 'healthchecks', purpose: 'A monitoring service that each job signals when it finishes, so a missed run raises an alarm.' },
];

export interface ServiceStatus {
  name: string;
  /** What the service is for, in plain words; empty for a service this page has no text for. */
  purpose: string;
  /** What the newest check got back ("HTTP 200"), and whether anything answered at all. */
  detail: string;
  answered: boolean;
  seconds: number | null;
  daysChecked: number;
  daysWithoutAnswer: number;
}

/** The outside services: every subject that is neither one of our jobs nor the pipeline timestamps. */
export function serviceStatuses(rows: HealthRow[]): ServiceStatus[] {
  const names = [...new Set(rows.filter((row) => row.metric === 'reachable').map((row) => row.subject))].sort();
  return names.map((name) => {
    const reach = rows.filter((row) => row.subject === name && row.metric === 'reachable').sort((a, b) => (a.day < b.day ? 1 : -1));
    const speed = rows.filter((row) => row.subject === name && row.metric === 'response_seconds' && row.value !== null).sort((a, b) => (a.day < b.day ? 1 : -1));
    return {
      name,
      purpose: SERVICE_PURPOSES.find((entry) => name.startsWith(entry.startsWith))?.purpose ?? '',
      detail: reach[0].detail,
      answered: reach[0].value === 1,
      seconds: speed.length === 0 ? null : (speed[0].value as number),
      daysChecked: reach.length,
      daysWithoutAnswer: reach.filter((row) => row.value !== 1).length,
    };
  });
}
