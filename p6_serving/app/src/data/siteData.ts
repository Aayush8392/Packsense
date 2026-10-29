import { parseCsv } from './csv';
import { createResource } from './resource';

export class DataError extends Error {}

export interface SiteStatus {
  /** When the daily publish built these files (UTC, ISO text). */
  builtAt: string;
  firstCompleteDay: string;
  lastCompleteDay: string;
  productsAll: number;
  productsIndia: number;
}

export interface ChangeRow {
  day: string;
  scope: string;
  group: string;
  openedBySeed: boolean;
  /** Products edited; null when the count was 1 to 4 and blanked on purpose. */
  products: number | null;
  periods: number | null;
  unseenEdits: number;
}

export interface HealthRow {
  day: string;
  subject: string;
  metric: string;
  value: number | null;
  unit: string;
  detail: string;
}

export interface QualityRow {
  day: string;
  scope: string;
  severity: string;
  /** The kind of flag: an Open Food Facts tag such as en:food-groups-warnings, or 'unmapped'. */
  family: string;
  /** Flags open that day; null when the count was 1 to 4 and blanked on purpose. */
  openFlags: number | null;
  /** Products PackSense held that day (the same on every row of a day and scope). */
  productsHeld: number;
}

function requireColumns(rows: Record<string, string>[], file: string, columns: string[]): void {
  if (rows.length === 0) throw new DataError(`${file} has no rows`);
  const missing = columns.filter((name) => !(name in rows[0]));
  if (missing.length > 0) throw new DataError(`${file} is missing the column ${missing.join(', ')}`);
}

/** A count column: a blank cell is a count of 1 to 4 that was hidden on purpose. */
function countOrNull(text: string, file: string): number | null {
  if (text.trim() === '') return null;
  const value = Number(text);
  if (!Number.isFinite(value)) throw new DataError(`${file} has a count that is not a number: ${text}`);
  return value;
}

function numberOf(text: string, file: string): number {
  const value = Number(text);
  if (text.trim() === '' || !Number.isFinite(value)) throw new DataError(`${file} has a value that is not a number: '${text}'`);
  return value;
}

export function parseSiteStatus(text: string): SiteStatus {
  const rows = parseCsv(text);
  requireColumns(rows, 'site_status.csv', ['built_at_utc', 'first_complete_day', 'last_complete_day', 'products_held_all', 'products_held_india']);
  const row = rows[0];
  return {
    builtAt: row.built_at_utc,
    firstCompleteDay: row.first_complete_day,
    lastCompleteDay: row.last_complete_day,
    productsAll: numberOf(row.products_held_all, 'site_status.csv'),
    productsIndia: numberOf(row.products_held_india, 'site_status.csv'),
  };
}

export function parseChangeDaily(text: string): ChangeRow[] {
  const rows = parseCsv(text);
  requireColumns(rows, 'change_daily.csv', ['change_date', 'scope', 'change_group', 'opened_by_seed', 'n_products', 'n_periods', 'unseen_edits']);
  return rows.map((row) => ({
    day: row.change_date,
    scope: row.scope,
    group: row.change_group,
    openedBySeed: row.opened_by_seed === '1',
    products: countOrNull(row.n_products, 'change_daily.csv'),
    periods: countOrNull(row.n_periods, 'change_daily.csv'),
    unseenEdits: Number(row.unseen_edits) || 0,
  }));
}

export function parseQualityDaily(text: string): QualityRow[] {
  const rows = parseCsv(text);
  requireColumns(rows, 'quality_daily.csv', ['snapshot_date', 'scope', 'severity', 'flag_family', 'open_spans', 'n_products_held']);
  return rows.map((row) => ({
    day: row.snapshot_date,
    scope: row.scope,
    severity: row.severity,
    family: row.flag_family,
    openFlags: countOrNull(row.open_spans, 'quality_daily.csv'),
    productsHeld: numberOf(row.n_products_held, 'quality_daily.csv'),
  }));
}

export function parsePipelineHealth(text: string): HealthRow[] {
  const rows = parseCsv(text);
  requireColumns(rows, 'pipeline_health.csv', ['metric_date', 'subject', 'metric', 'value', 'unit', 'detail']);
  return rows.map((row) => ({
    day: row.metric_date,
    subject: row.subject,
    metric: row.metric,
    value: row.value.trim() === '' ? null : numberOf(row.value, 'pipeline_health.csv'),
    unit: row.unit,
    detail: row.detail,
  }));
}

/** Where the published files are served from: the app's own `data/` folder, next to the page. */
export function dataUrl(name: string): string {
  return `${import.meta.env.BASE_URL}data/${name}`;
}

export async function fetchText(name: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(dataUrl(name));
  } catch {
    throw new DataError(`${name} could not be reached`);
  }
  if (!response.ok) throw new DataError(`${name} could not be loaded (${response.status})`);
  const text = await response.text();
  // A server that answers an unknown file with its home page must not be mistaken for data.
  if (/^\s*</.test(text)) throw new DataError(`${name} is not a data file`);
  return text;
}

export const siteStatus = createResource(async () => parseSiteStatus(await fetchText('site_status.csv')));
export const changeDaily = createResource(async () => parseChangeDaily(await fetchText('change_daily.csv')));
export const qualityDaily = createResource(async () => parseQualityDaily(await fetchText('quality_daily.csv')));
export const pipelineHealth = createResource(async () => parsePipelineHealth(await fetchText('pipeline_health.csv')));
