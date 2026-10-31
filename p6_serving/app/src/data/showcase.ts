import { flagName } from './flagNames';
import { createResource } from './resource';
import { DataError, fetchText } from './siteData';
import { signalFor } from './signals';
import { formatCount, formatDay, utcDay } from '../format';

type Row = Record<string, unknown>;

export interface ShowcaseProduct {
  key: string;
  code: string;
  name: string;
  brand: string;
  bronze: { record: Row; counts: Record<string, number> };
  silver: { row: Row; counts: Row };
  gold: Record<string, Row[]>;
}

export interface Showcase {
  builtAt: string;
  /** The text that stands where something was removed or hidden on purpose. */
  markers: { images: string; hidden: string };
  standIns: string[];
  products: ShowcaseProduct[];
}

/** The eight gold tables every product carries, in the order the page shows them. */
export const GOLD_TABLES = [
  'product_history', 'product_flag_spans', 'product_nutrition_sets', 'product_rule_verdicts',
  'mart_product_card', 'mart_brand_scorecard', 'fct_product_change_daily', 'fct_catalogue_quality_daily',
] as const;
export type GoldTable = (typeof GOLD_TABLES)[number];

const isObject = (value: unknown): value is Row => typeof value === 'object' && value !== null && !Array.isArray(value);

/** Reads and checks the showcase file. A file of the wrong shape is refused, never shown half-way. */
export function parseShowcase(text: string): Showcase {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new DataError('showcase.json is not readable');
  }
  if (!isObject(raw) || raw.version !== 1) throw new DataError('showcase.json is not a version 1 file');
  const markers = raw.markers;
  if (!isObject(markers) || typeof markers.images !== 'string' || typeof markers.hidden !== 'string') throw new DataError('showcase.json has no markers');
  if (!Array.isArray(raw.stand_ins) || !Array.isArray(raw.products) || raw.products.length === 0) throw new DataError('showcase.json has no products');
  const products = raw.products.map((p: unknown): ShowcaseProduct => {
    if (!isObject(p) || typeof p.key !== 'string' || typeof p.code !== 'string' || typeof p.name !== 'string') throw new DataError('showcase.json has a product without a key, code or name');
    const { bronze, silver, gold } = p;
    if (!isObject(bronze) || !isObject(bronze.record) || !isObject(bronze.counts)) throw new DataError(`showcase.json: ${p.key} has no raw record`);
    if (!isObject(silver) || !isObject(silver.row) || !isObject(silver.counts)) throw new DataError(`showcase.json: ${p.key} has no cleaned row`);
    if (!isObject(gold)) throw new DataError(`showcase.json: ${p.key} has no gold tables`);
    for (const table of GOLD_TABLES) if (!Array.isArray(gold[table])) throw new DataError(`showcase.json: ${p.key} is missing the table ${table}`);
    return {
      key: p.key, code: p.code, name: p.name, brand: typeof p.brand === 'string' ? p.brand : '',
      bronze: { record: bronze.record, counts: bronze.counts as Record<string, number> },
      silver: { row: silver.row, counts: silver.counts },
      gold: gold as Record<string, Row[]>,
    };
  });
  return {
    builtAt: typeof raw.built_at_utc === 'string' ? raw.built_at_utc : '',
    markers: { images: markers.images, hidden: markers.hidden },
    standIns: raw.stand_ins.map(String),
    products,
  };
}

export const showcase = createResource(async () => parseShowcase(await fetchText('showcase.json')));

/** Why each of the four products was picked, in plain words. The number of versions comes from the data. */
export function reasonFor(product: ShowcaseProduct): string {
  const card = product.gold.mart_product_card[0] ?? {};
  switch (product.key) {
    case 'ordinary_food': return 'An ordinary packaged food.';
    case 'several_flags': return 'A product that carries several flags.';
    case 'long_history': return `A long edit history: ${card.versions_kept ?? 'many'} versions kept.`;
    case 'india': return 'A product from India.';
    default: return '';
  }
}

// ----- what a value looks like on the page ------------------------------------------------------------------------------------------------------

/** One value as short text: null is a dash, a list is its items, an object is shown compactly. `full` is the whole text when `short` was cut. */
export function describeValue(value: unknown, limit = 120): { short: string; full: string | null } {
  let text: string;
  if (value === null || value === undefined) text = '—';
  else if (typeof value === 'boolean') text = value ? 'yes' : 'no';
  else if (typeof value === 'string') text = value === '' ? '(empty)' : value;
  else if (typeof value === 'number') text = String(value);
  else text = JSON.stringify(value);
  return text.length > limit ? { short: `${text.slice(0, limit)}…`, full: text } : { short: text, full: null };
}

export interface ListRow {
  key: string;
  short: string;
  full: string | null;
  /** The text of a hidden or removed value, kept so the page can mark it. */
  hidden: boolean;
}

/** The raw record as a list of keys and values, in file order. Values removed on purpose are marked. */
export function rawRows(product: ShowcaseProduct, markers: Showcase['markers']): ListRow[] {
  return Object.entries(product.bronze.record).map(([key, value]) => ({ key, ...describeValue(value), hidden: value === markers.images }));
}

/** The cleaned row as a list of columns. The columns hidden on purpose carry the hidden marker as their value. */
export function silverRows(product: ShowcaseProduct, markers: Showcase['markers']): ListRow[] {
  return Object.entries(product.silver.row).map(([key, value]) => ({ key, ...describeValue(value), hidden: value === markers.hidden }));
}

export function searchRows(rows: ListRow[], query: string): ListRow[] {
  const needle = query.trim().toLowerCase();
  if (needle === '') return rows;
  return rows.filter((row) => row.key.toLowerCase().includes(needle) || (row.full ?? row.short).toLowerCase().includes(needle));
}

// ----- "the same field, three steps" -----------------------------------------------------------------------------------------------------------

export interface SameField {
  field: string;
  raw: string;
  silver: string;
  gold: string;
}

/** The nutrition set of the packaging, per 100 g or 100 ml, as the raw record holds it: its energy value as text. */
export function rawEnergy(record: Row): string {
  const nutrition = record.nutrition;
  if (!isObject(nutrition) || !Array.isArray(nutrition.input_sets)) return '—';
  const sets = nutrition.input_sets.filter(isObject);
  const wanted = sets.find((s) => s.source === 'packaging' && (s.per === '100g' || s.per === '100ml'));
  const kcal = wanted && isObject(wanted.nutrients) && isObject(wanted.nutrients['energy-kcal']) ? wanted.nutrients['energy-kcal'] : null;
  if (!kcal) return `${sets.length} separate sets, none with energy per 100 g`;
  return `energy-kcal "${kcal.value_string ?? kcal.value}" in the packaging set per ${wanted?.per}; the record holds ${sets.length} separate sets`;
}

export function sameFieldRows(product: ShowcaseProduct): SameField[] {
  const raw = product.bronze.record;
  const silver = product.silver.row;
  const history = product.gold.product_history;
  const latest = history.find((row) => row.is_latest_observed === true || row.is_latest_observed === 1) ?? history[history.length - 1] ?? {};
  const text = (value: unknown) => describeValue(value, 90).short;
  const kcal = silver.energy_kcal;
  return [
    { field: 'Name', raw: `product_name: ${text(raw.product_name)}`, silver: `product_name: ${text(silver.product_name)}`, gold: `product history, product_name: ${text(latest.product_name)}` },
    {
      field: 'Pack size',
      raw: `quantity: ${text(raw.quantity)} (one text)`,
      silver: `quantity_amount: ${text(silver.quantity_amount)}, quantity_unit: ${text(silver.quantity_unit)} (split into a number and a unit)`,
      gold: `product history, quantity_amount: ${text(latest.quantity_amount)}, quantity_unit: ${text(latest.quantity_unit)}`,
    },
    {
      field: 'Categories',
      raw: `categories_tags: ${text(raw.categories_tags)}`,
      silver: `categories_tags: ${text(silver.categories_tags)}`,
      gold: `product history, categories_tags: ${text(latest.categories_tags)}`,
    },
    {
      field: 'Energy per 100 g',
      raw: rawEnergy(raw),
      silver: `energy_kcal: ${text(kcal)} (the figure chosen from the sets)`,
      gold: `product history, energy_kcal: ${text(latest.energy_kcal)}; nutrition sets, one row for each of the ${product.gold.product_nutrition_sets.length} sets`,
    },
  ];
}

// ----- the gold tables --------------------------------------------------------------------------------------------------------------------------

export interface GoldColumn {
  key: string;
  label: string;
  /** How the cell is written; the default is the plain value. */
  as?: 'date' | 'count' | 'flag' | 'signal' | 'yesno' | 'number';
}

export interface GoldView {
  table: GoldTable;
  /** Rows to a page when 10 would split a set that belongs together. */
  pageSize?: number;
  title: string;
  note: string;
  columns: GoldColumn[];
}

/** For each gold table: a plain title, a line saying what it is, and the readable subset of its columns (the full tables are wider). */
export const GOLD_VIEWS: GoldView[] = [
  {
    table: 'product_history', title: 'Version history',
    note: 'One row for each period in which the product looked the same. A new row starts when a tracked field changes.',
    columns: [
      { key: 'valid_from', label: 'From', as: 'date' }, { key: 'valid_to', label: 'To', as: 'date' }, { key: 'rev_at_open', label: 'Revision' },
      { key: 'product_name', label: 'Name' }, { key: 'brands', label: 'Brand' }, { key: 'quantity_amount', label: 'Pack size' },
      { key: 'energy_kcal', label: 'Energy (kcal)', as: 'number' }, { key: 'sugars', label: 'Sugars (g)', as: 'number' }, { key: 'salt', label: 'Salt (g)', as: 'number' },
      { key: 'nutriscore_grade', label: 'Nutri-Score' }, { key: 'nova_group', label: 'NOVA' }, { key: 'is_latest_observed', label: 'Newest', as: 'yesno' },
    ],
  },
  {
    table: 'product_flag_spans', title: 'Flags it carried',
    note: 'One row for each flag, with when it was first and last seen. A flag means worth a look, not wrong.',
    columns: [
      { key: 'severity', label: 'How serious' }, { key: 'flag', label: 'Kind of flag', as: 'flag' }, { key: 'first_seen_t', label: 'First seen', as: 'date' },
      { key: 'last_seen_t', label: 'Last seen', as: 'date' }, { key: 'versions_present', label: 'Versions' }, { key: 'is_open', label: 'Still open', as: 'yesno' },
    ],
  },
  {
    table: 'product_nutrition_sets', title: 'Nutrition, by source',
    note: 'The product can carry several sets of nutrition figures: from the pack, per serving, or estimated from the ingredients.',
    columns: [
      { key: 'source', label: 'Source' }, { key: 'preparation', label: 'Preparation' }, { key: 'per', label: 'Per' }, { key: 'energy_kcal', label: 'Energy (kcal)', as: 'number' },
      { key: 'fat', label: 'Fat (g)', as: 'number' }, { key: 'sugars', label: 'Sugars (g)', as: 'number' }, { key: 'salt', label: 'Salt (g)', as: 'number' }, { key: 'proteins', label: 'Protein (g)', as: 'number' },
    ],
  },
  {
    table: 'product_rule_verdicts', title: 'The arithmetic checks', pageSize: 11,
    note: "PackSense's own checks on the nutrition figures, run for each set. \"Not applicable\" means the check could not be run on that set.",
    columns: [
      { key: 'rule', label: 'Check' }, { key: 'source', label: 'Source' }, { key: 'per', label: 'Per' }, { key: 'status', label: 'Result' },
      { key: 'severity', label: 'How serious' }, { key: 'deviation', label: 'Difference', as: 'number' },
    ],
  },
  {
    table: 'mart_product_card', title: 'The product card',
    note: 'The summary this site shows for a barcode: a signal and the counts under it.',
    columns: [
      { key: 'light', label: 'Signal', as: 'signal' }, { key: 'off_error', label: 'OFF errors' }, { key: 'off_bug', label: 'OFF bugs' }, { key: 'off_warning', label: 'OFF warnings' },
      { key: 'rules_failed', label: 'Checks failed' }, { key: 'rules_checkable', label: 'Checks run' }, { key: 'fields_filled', label: 'Of 7 fields filled' },
      { key: 'versions_kept', label: 'Versions kept' }, { key: 'last_edit_t', label: 'Last edit', as: 'date' }, { key: 'in_india', label: 'In India', as: 'yesno' },
    ],
  },
  {
    table: 'mart_brand_scorecard', title: "Its brand's scorecard row",
    note: 'How completely the brand fills the seven things across all its products, as of the date shown.',
    columns: [
      { key: 'brand_name', label: 'Brand' }, { key: 'n_products', label: 'Products', as: 'count' }, { key: 'n_with_nutrition', label: 'With nutrition', as: 'count' },
      { key: 'n_with_nutriscore', label: 'With Nutri-Score', as: 'count' }, { key: 'n_with_nova', label: 'With NOVA', as: 'count' }, { key: 'n_with_quantity', label: 'With pack size', as: 'count' },
      { key: 'n_with_ingredients', label: 'With ingredients', as: 'count' }, { key: 'n_with_categories', label: 'With categories', as: 'count' }, { key: 'n_with_labels', label: 'With labels', as: 'count' },
    ],
  },
  {
    table: 'fct_product_change_daily', title: 'Daily changes (a few rows)',
    note: 'The daily summary of what people edited, as shown on the Daily changes page.',
    columns: [
      { key: 'change_date', label: 'Day', as: 'date' }, { key: 'scope', label: 'Scope' }, { key: 'change_group', label: 'Kind of edit' },
      { key: 'n_products', label: 'Products edited', as: 'count' }, { key: 'unseen_edits', label: 'Edits between files', as: 'count' },
    ],
  },
  {
    table: 'fct_catalogue_quality_daily', title: 'Daily quality (a few rows)',
    note: 'The daily count of open flags, as shown on the Data quality page.',
    columns: [
      { key: 'snapshot_date', label: 'Day', as: 'date' }, { key: 'scope', label: 'Scope' }, { key: 'severity', label: 'How serious' }, { key: 'flag_family', label: 'Kind of flag', as: 'flag' },
      { key: 'open_spans', label: 'Open flags', as: 'count' }, { key: 'n_products_held', label: 'Products held', as: 'count' },
    ],
  },
];

/** A table cell as text. A null is a dash. Seconds since 1970 are written as a day. */
export function goldCell(value: unknown, as: GoldColumn['as']): string {
  if (value === null || value === undefined) return '—';
  switch (as) {
    case 'date': {
      if (typeof value === 'number') return formatDay(utcDay(new Date(value * 1000)));
      return typeof value === 'string' && value.length >= 10 ? formatDay(value) : String(value);
    }
    case 'count': return typeof value === 'number' ? formatCount(value) : String(value);
    case 'number': return typeof value === 'number' ? String(Number(value.toFixed(4))) : String(value);
    case 'yesno': return value === true || value === 1 ? 'yes' : value === false || value === 0 ? 'no' : String(value);
    case 'flag': return typeof value === 'string' ? flagName(value).name : String(value);
    case 'signal': return typeof value === 'string' ? signalFor(value).label : String(value);
    default: return describeValue(value, 80).short;
  }
}

// ----- what was done to the record before it is shown ------------------------------------------------------------------------------------------

export interface DoneRow {
  count: number;
  text: string;
}

/** The counts the export recorded for this product, each with a plain sentence. A count of zero is still listed: nothing was needed. */
export function doneRows(product: ShowcaseProduct): DoneRow[] {
  const raw = product.bronze.counts;
  const silver = product.silver.counts;
  const num = (value: unknown) => (typeof value === 'number' ? value : 0);
  return [
    { count: num(raw.contributor_fields_replaced), text: 'fields that name volunteers, replaced with stand-in names such as contributor-A' },
    { count: num(raw.names_replaced_in_text), text: "volunteers' names found inside ordinary text, replaced" },
    { count: num(raw.keys_renamed), text: "field names that were themselves a volunteer's name, renamed" },
    { count: num(raw.image_fields_marked), text: 'image fields, replaced with a marker' },
    { count: num(raw.patterns_removed), text: 'pieces of text that looked like an email address, web link, phone number or personal ID, removed' },
    { count: num(silver.silver_columns_hidden), text: 'columns of the cleaned row hidden on purpose' },
    { count: num(silver.tag_values_dropped_total), text: 'tag values dropped because they did not look like tags' },
  ];
}
