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
  /** Flags that appeared that day on a product PackSense already held; null when the count was 1 to 4 and blanked on purpose. */
  appeared: number | null;
  /** Flags that ended that day: fixed, or the product left (the file does not tell the two apart); null when blanked. */
  ended: number | null;
  /** Flags on a product's first version we saw: the product arrived already flagged. Null when blanked, or when the file has no such column. */
  carriedIn: number | null;
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
  requireColumns(rows, 'quality_daily.csv', ['snapshot_date', 'scope', 'severity', 'flag_family', 'open_spans', 'opened_on_known_product', 'vanished', 'n_products_held']);
  return rows.map((row) => ({
    day: row.snapshot_date,
    scope: row.scope,
    severity: row.severity,
    family: row.flag_family,
    openFlags: countOrNull(row.open_spans, 'quality_daily.csv'),
    productsHeld: numberOf(row.n_products_held, 'quality_daily.csv'),
    appeared: countOrNull(row.opened_on_known_product, 'quality_daily.csv'),
    ended: countOrNull(row.vanished, 'quality_daily.csv'),
    carriedIn: row.carried_in === undefined ? null : countOrNull(row.carried_in, 'quality_daily.csv'),
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

/** One week of the whole of Open Food Facts (not only the products PackSense holds), from OFF's own weekly snapshots. Counts of 1 to 4 are null. */
export interface OffWeeklyRow {
  /** The date of the newer of the two snapshots the week compares. */
  weekEnd: string;
  productsHeld: number;
  productsAdded: number | null;
  productsRemoved: number | null;
  productsEdited: number | null;
  /** Flags that ended on products present in both snapshots (a flag renamed to another of the same family is not an end), by severity. */
  endedError: number | null;
  endedWarning: number | null;
  endedInfo: number | null;
  appearedError: number | null;
  appearedWarning: number | null;
  appearedInfo: number | null;
}

/** Open flags over the whole of OFF at one weekly snapshot, for one severity and kind of flag. */
export interface OffOpenFlagRow {
  day: string;
  severity: string;
  /** An OFF flag family such as 'value-total-over-105', or the one row that adds up every kind outside the largest forty. */
  kind: string;
  openFlags: number | null;
}

export const OFF_OTHER_KIND = '(all other kinds)';

export function parseOffWeekly(text: string): OffWeeklyRow[] {
  const file = 'off_weekly.csv';
  const rows = parseCsv(text);
  requireColumns(rows, file, ['week_end', 'products_held', 'products_added', 'products_removed', 'products_edited', 'flags_ended_error', 'flags_ended_warning',
    'flags_ended_info', 'flags_appeared_error', 'flags_appeared_warning', 'flags_appeared_info']);
  return rows.map((row) => ({
    weekEnd: row.week_end,
    productsHeld: numberOf(row.products_held, file),
    productsAdded: countOrNull(row.products_added, file),
    productsRemoved: countOrNull(row.products_removed, file),
    productsEdited: countOrNull(row.products_edited, file),
    endedError: countOrNull(row.flags_ended_error, file),
    endedWarning: countOrNull(row.flags_ended_warning, file),
    endedInfo: countOrNull(row.flags_ended_info, file),
    appearedError: countOrNull(row.flags_appeared_error, file),
    appearedWarning: countOrNull(row.flags_appeared_warning, file),
    appearedInfo: countOrNull(row.flags_appeared_info, file),
  }));
}

export function parseOffOpenFlags(text: string): OffOpenFlagRow[] {
  const file = 'off_open_flags.csv';
  const rows = parseCsv(text);
  requireColumns(rows, file, ['snapshot_date', 'severity', 'kind', 'open_flags']);
  return rows.map((row) => ({ day: row.snapshot_date, severity: row.severity, kind: row.kind, openFlags: countOrNull(row.open_flags, file) }));
}

export const offWeekly = createResource(async () => parseOffWeekly(await fetchText('off_weekly.csv')));
export const offOpenFlags = createResource(async () => parseOffOpenFlags(await fetchText('off_open_flags.csv')));

/** One top-level category with at least 200 products, as PackSense holds them: how many of its products fill each of four things. */
export interface CategoryRow {
  scope: string;
  /** An Open Food Facts category tag such as 'en:biscuits'. */
  category: string;
  asOf: string;
  products: number;
  fiveNutrients: number | null;
  ingredients: number | null;
  quantity: number | null;
}

/** How many products one of OFF's arithmetic checks could be decided for, and how many of those it flags. Null when the count was 1 to 4. */
export interface RuleCheckRow {
  scope: string;
  /** The family of the flag the check matches, such as 'salt-does-not-match-sodium'. */
  rule: string;
  checked: number | null;
  flagged: number | null;
}

/** How many nutrition tables (sets) and products come from one source. Null when the count was 1 to 4. */
export interface NutritionSourceRow {
  scope: string;
  source: string;
  sets: number | null;
  products: number | null;
}

export function parseCategoryFitness(text: string): CategoryRow[] {
  const file = 'category_fitness.csv';
  const rows = parseCsv(text);
  requireColumns(rows, file, ['scope', 'category', 'as_of_date', 'n_products', 'n_five_nutrients', 'n_with_ingredients', 'n_with_quantity']);
  return rows.map((row) => ({
    scope: row.scope,
    category: row.category,
    asOf: row.as_of_date,
    products: numberOf(row.n_products, file),
    fiveNutrients: countOrNull(row.n_five_nutrients, file),
    ingredients: countOrNull(row.n_with_ingredients, file),
    quantity: countOrNull(row.n_with_quantity, file),
  }));
}

export function parseRuleChecks(text: string): RuleCheckRow[] {
  const file = 'rule_checks.csv';
  const rows = parseCsv(text);
  requireColumns(rows, file, ['scope', 'rule', 'n_products_checked', 'n_products_flagged']);
  return rows.map((row) => ({ scope: row.scope, rule: row.rule, checked: countOrNull(row.n_products_checked, file), flagged: countOrNull(row.n_products_flagged, file) }));
}

export function parseNutritionSources(text: string): NutritionSourceRow[] {
  const file = 'nutrition_sources.csv';
  const rows = parseCsv(text);
  requireColumns(rows, file, ['scope', 'source', 'n_sets', 'n_products']);
  return rows.map((row) => ({ scope: row.scope, source: row.source, sets: countOrNull(row.n_sets, file), products: countOrNull(row.n_products, file) }));
}

export const categoryFitness = createResource(async () => parseCategoryFitness(await fetchText('category_fitness.csv')));
export const ruleChecks = createResource(async () => parseRuleChecks(await fetchText('rule_checks.csv')));
export const nutritionSources = createResource(async () => parseNutritionSources(await fetchText('nutrition_sources.csv')));
