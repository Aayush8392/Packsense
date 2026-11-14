import { describeValue, type Showcase, type ShowcaseProduct } from '../data/showcase';

/** One field of the record as it is in the raw copy and as it ends up in the cleaned copy. */
export interface RowPair {
  fromKey: string;
  fromValue: string;
  toKey: string;
  toValue: string;
  /** The row that holds a volunteer's (stand-in) username in the raw copy. */
  user: boolean;
}

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
  /** The fields that are kept (and renamed or hidden on the way) and, after them, raw fields the cleaned copy does not keep. */
  pairs: RowPair[];
  dropped: StoryRow[];
  tables: StoryTable[];
  tableCount: number;
  flagRows: number;
  nutritionRows: number;
  changeRows: number;
}

/** Each raw field that has a cleaned counterpart, and the name that counterpart has. */
const KEPT: [string, string][] = [
  ['_id', 'code'],
  ['product_name_fr', 'product_name'],
  ['creator', 'creator_hmac'],
  ['nutriscore_2021_tags', 'nutriscore_grade'],
  ['ingredients_text', 'ingredients_sha256'],
];
const SHOWN_TABLES = ['product_history', 'product_flag_spans', 'product_nutrition_sets', 'product_rule_verdicts'];

/** The story's figures and rows from the showcase file; null when the file has no usable product. */
export function storyFrom(showcase: Showcase): StoryData | null {
  const product: ShowcaseProduct | undefined = showcase.products.find((p) => p.key === 'ordinary_food') ?? showcase.products[0];
  if (!product) return null;
  const record = product.bronze.record;
  const clean = product.silver.row;
  const counts = product.silver.counts;
  const gold = product.gold;
  const marker = showcase.markers.hidden;
  const rows = (table: string) => (gold[table] ?? []).length;
  const text = (value: unknown) => describeValue(value, 22).short;

  const pairs: RowPair[] = KEPT.filter(([from, to]) => from in record && to in clean).map(([from, to]) => ({
    fromKey: from,
    fromValue: text(record[from]),
    toKey: to,
    toValue: clean[to] === marker ? marker : text(clean[to]),
    user: from === 'creator',
  }));
  const keptKeys = new Set(KEPT.map(([from]) => from));
  const dropped = Object.keys(record)
    .filter((key) => /^[a-z][a-z_]+$/.test(key) && !(key in clean) && !keptKeys.has(key) && key.length < 26)
    .slice(0, 3)
    .map((key) => ({ key, value: text(record[key]) }));

  return {
    name: product.name,
    code: product.code,
    rawFields: Number(counts.raw_top_level_fields ?? Object.keys(record).length),
    silverColumns: Number(counts.silver_columns ?? Object.keys(clean).length),
    pairs,
    dropped,
    tables: SHOWN_TABLES.map((name) => ({ name, rows: rows(name) })),
    tableCount: Object.keys(gold).length,
    flagRows: rows('product_flag_spans'),
    nutritionRows: rows('product_nutrition_sets'),
    changeRows: rows('fct_product_change_daily'),
  };
}
