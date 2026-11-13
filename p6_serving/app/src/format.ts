const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** 155134 becomes "155,134". */
export function formatCount(value: number): string {
  return value.toLocaleString('en-GB');
}

/** Flags per product: two decimals below 1 (so 0.05 and 0.10 stay apart), one decimal above, without a trailing zero. 9.43 becomes "9.4". */
export function formatPerProduct(value: number): string {
  return value < 1 ? value.toFixed(2) : String(Number(value.toFixed(1)));
}

/** "2026-10-27" becomes "27 Oct 2026". */
export function formatDay(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** "2026-10-31" is "31 Oct 2026" for a day or a week ending that day, and "Oct 2026" for a month. */
export function formatPeriod(iso: string, grain: 'day' | 'week' | 'month'): string {
  if (grain !== 'month') return formatDay(iso);
  const [year, month] = iso.slice(0, 10).split('-').map(Number);
  return `${MONTHS[month - 1]} ${year}`;
}

/** The UTC calendar day of a moment, as "2026-10-27". */
export function utcDay(moment: Date): string {
  return moment.toISOString().slice(0, 10);
}

/** India Standard Time is UTC+05:30 all year (no daylight saving). */
const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;

/** Moves a moment so that its UTC fields read as the clock on the wall in India. */
function toIst(moment: Date): Date {
  return new Date(moment.getTime() + IST_OFFSET_MS);
}

/** The calendar day in India of a moment, as "2026-10-27". */
export function istDay(moment: Date): string {
  return toIst(moment).toISOString().slice(0, 10);
}

/** The clock time in India of a moment, as "12:15 IST". */
export function istTime(moment: Date): string {
  return `${toIst(moment).toISOString().slice(11, 16)} IST`;
}

function addDays(iso: string, days: number): string {
  const moment = new Date(`${iso}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return utcDay(moment);
}

/** A moment in plain words relative to now, on the clock and calendar in India: "today, 12:01 IST", "yesterday, 12:01 IST" or "23 Oct, 12:01 IST". */
export function describeMoment(moment: Date, now: Date): string {
  const day = istDay(moment);
  const today = istDay(now);
  if (day === today) return `today, ${istTime(moment)}`;
  if (day === addDays(today, -1)) return `yesterday, ${istTime(moment)}`;
  const [, month, dayOfMonth] = day.split('-').map(Number);
  return `${dayOfMonth} ${MONTHS[month - 1]}, ${istTime(moment)}`;
}

export { addDays };

/** A large count in short form for a chart axis: 950, 12k, 261k, 4.89M, 22.5M. Tables keep the full number. */
export function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs < 1000) return String(Math.round(value));
  if (abs < 10_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  if (abs < 1_000_000) return `${Math.round(value / 1000)}k`;
  return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 1 : 2).replace(/\.?0+$/, '')}M`;
}
