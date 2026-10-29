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

/** The UTC calendar day of a moment, as "2026-10-27". */
export function utcDay(moment: Date): string {
  return moment.toISOString().slice(0, 10);
}

function utcTime(moment: Date): string {
  return `${moment.toISOString().slice(11, 16)} UTC`;
}

function addDays(iso: string, days: number): string {
  const moment = new Date(`${iso}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return utcDay(moment);
}

/** A moment in plain words relative to now: "today, 06:31 UTC", "yesterday, 06:31 UTC" or "23 Oct, 06:31 UTC". */
export function describeMoment(moment: Date, now: Date): string {
  const day = utcDay(moment);
  const today = utcDay(now);
  if (day === today) return `today, ${utcTime(moment)}`;
  if (day === addDays(today, -1)) return `yesterday, ${utcTime(moment)}`;
  const [, month, dayOfMonth] = day.split('-').map(Number);
  return `${dayOfMonth} ${MONTHS[month - 1]}, ${utcTime(moment)}`;
}

export { addDays };
