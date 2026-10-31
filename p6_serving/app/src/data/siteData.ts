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

/** One brand's row of the scorecard: how many of its products fill each of the seven things, on the day the file was made. */
export interface BrandRow {
  scope: string;
  /** The first brand listed on the product, in lower case (the file's own grouping). */
  name: string;
  asOf: string;
  products: number;
  /** Products that fill each thing; the keys are the ones in `ITEMS` (data/brands.ts). */
  filled: Record<string, number>;
  /** The file's own total of the seven counts. */
  points: number;
  /** Products that fill exactly 0, 1, ... 7 of the seven things (index = how many). Null until the published file carries the columns. */
  spread: number[] | null;
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

const BRAND_COLUMNS: [key: string, column: string][] = [
  ['nutrition', 'n_with_nutrition'],
  ['nutriscore', 'n_with_nutriscore'],
  ['nova', 'n_with_nova'],
  ['quantity', 'n_with_quantity'],
  ['ingredients', 'n_with_ingredients'],
  ['categories', 'n_with_categories'],
  ['labels', 'n_with_labels'],
];

const SPREAD_COLUMNS = Array.from({ length: 8 }, (_, count) => `n_filled_${count}`);

export function parseBrandScorecard(text: string): BrandRow[] {
  const file = 'brand_scorecard.csv';
  const rows = parseCsv(text);
  requireColumns(rows, file, ['scope', 'brand_name', 'as_of_date', 'n_products', 'coverage_points', ...BRAND_COLUMNS.map(([, column]) => column)]);
  // The eight "exactly this many" columns arrive with the next gold build; a file without them still loads, and the page leaves out the details.
  const hasSpread = SPREAD_COLUMNS.every((column) => column in rows[0]);
  return rows.map((row) => {
    const products = numberOf(row.n_products, file);
    const filled = Object.fromEntries(BRAND_COLUMNS.map(([key, column]) => [key, numberOf(row[column], file)]));
    if (products <= 0) throw new DataError(`${file} has a brand with no products`);
    if (Object.values(filled).some((count) => count > products)) throw new DataError(`${file} has a brand that fills a thing for more products than it has`);
    const points = numberOf(row.coverage_points, file);
    let spread: number[] | null = null;
    if (hasSpread) {
      spread = SPREAD_COLUMNS.map((column) => numberOf(row[column], file));
      if (spread.reduce((sum, count) => sum + count, 0) !== products) throw new DataError(`${file} has a brand whose product groups do not add up to its products`);
      if (spread.reduce((sum, count, filledCount) => sum + count * filledCount, 0) !== points) throw new DataError(`${file} has a brand whose product groups do not match its points`);
    }
    return { scope: row.scope, name: row.brand_name, asOf: row.as_of_date, products, filled, points, spread };
  });
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
export const brandScorecard = createResource(async () => parseBrandScorecard(await fetchText('brand_scorecard.csv')));
