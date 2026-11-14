import { describeValue, type Showcase, type ShowcaseProduct } from '../data/showcase';

export interface StoryRow {
  key: string;
  value: string;
}

export interface StoryTable {
  name: string;
  rows: number;
}

/** What the story shows, taken from one real product of the showcase file, so none of its figures is typed in by hand. */
export interface StoryData {
  name: string;
  code: string;
  rawFields: number;
  silverColumns: number;
  hiddenColumns: number;
  /** A few raw fields; the one named `userField` holds a volunteer's (stand-in) username. */
  rawRows: StoryRow[];
  userField: string;
  userValue: string;
  /** The same product's cleaned row: the columns `cleanRows` and the hidden column that replaced the username. */
  cleanRows: StoryRow[];
  hiddenField: string;
  /** Raw fields that the cleaned copy does not keep: they fall away in the story. */
  droppedKeys: string[];
  tables: StoryTable[];
  tableCount: number;
  flagRows: number;
  nutritionRows: number;
  changeRows: number;
}

const RAW_KEYS = ['_id', 'product_name_fr', 'creator', 'nutriscore_2021_tags', 'ingredients_text'];
const CLEAN_KEYS = ['code', 'product_name', 'creator_hmac', 'nutriscore_grade'];
const SHOWN_TABLES = ['product_history', 'product_flag_spans', 'product_nutrition_sets', 'product_rule_verdicts'];

function rowsOf(source: Record<string, unknown>, keys: string[], marker: string): StoryRow[] {
  return keys
    .filter((key) => key in source)
    .map((key) => ({ key, value: describeValue(source[key] === marker ? marker : source[key], 28).short }));
}

/** The story's figures and rows from the showcase file; null when the file has no usable product. */
export function storyFrom(showcase: Showcase): StoryData | null {
  const product: ShowcaseProduct | undefined = showcase.products.find((p) => p.key === 'ordinary_food') ?? showcase.products[0];
  if (!product) return null;
  const hiddenMarker = showcase.markers.hidden;
  const record = product.bronze.record;
  const counts = product.silver.counts;
  const gold = product.gold;
  const rows = (table: string) => (gold[table] ?? []).length;
  const raw = Number(counts.raw_top_level_fields ?? Object.keys(record).length);
  const columns = Number(counts.silver_columns ?? Object.keys(product.silver.row).length);
  return {
    name: product.name,
    code: product.code,
    rawFields: raw,
    silverColumns: columns,
    hiddenColumns: Number(counts.silver_columns_hidden ?? 0),
    rawRows: rowsOf(record, RAW_KEYS, hiddenMarker),
    userField: 'creator',
    userValue: describeValue(record.creator, 28).short,
    cleanRows: rowsOf(product.silver.row, CLEAN_KEYS, hiddenMarker),
    hiddenField: 'creator_hmac',
    droppedKeys: Object.keys(record)
      .filter((key) => /^[a-z][a-z_]+$/.test(key) && !(key in product.silver.row) && !RAW_KEYS.includes(key) && key.length < 26)
      .slice(0, 3),
    tables: SHOWN_TABLES.map((name) => ({ name, rows: rows(name) })),
    tableCount: Object.keys(gold).length,
    flagRows: rows('product_flag_spans'),
    nutritionRows: rows('product_nutrition_sets'),
    changeRows: rows('fct_product_change_daily'),
  };
}
