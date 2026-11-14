import { readableTag, flagName } from '../data/flagNames';
import { describeValue, type Showcase, type ShowcaseProduct } from '../data/showcase';
import { formatDay } from '../format';

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

/** One flag of a product with a long history: where on the date axis (0 to 1) it began and ended. */
export interface FlagBar {
  label: string;
  severity: string;
  from: number;
  to: number;
  /** True when the flag went away (the product was edited and the flag no longer applied) before the last day. */
  ended: boolean;
}

export interface HistoryStory {
  name: string;
  versions: number;
  startLabel: string;
  endLabel: string;
  bars: FlagBar[];
  flagCount: number;
}

export interface CheckRow {
  label: string;
  /** True when the product's figures agree with the rule. */
  ok: boolean;
}

export interface ChecksStory {
  name: string;
  rows: CheckRow[];
  ok: number;
  bad: number;
}

/** What the story shows, taken from real products of the showcase file, so none of its figures is typed in by hand. */
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
  /** The product with the longest history, whose flags came and went. */
  history: HistoryStory;
  /** The product whose figures disagree with the most arithmetic rules. */
  checks: ChecksStory;
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
const MAX_BARS = 8;

const seconds = (value: unknown): number | null => {
  const n = Number(value);
  return value === null || value === undefined || value === 'None' || !Number.isFinite(n) ? null : n;
};
const dayOf = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);

function historyOf(product: ShowcaseProduct): HistoryStory | null {
  const spans = product.gold.product_flag_spans ?? [];
  const firsts = spans.map((s) => seconds(s.first_seen_t)).filter((t): t is number => t !== null);
  if (firsts.length === 0) return null;
  const ends = spans.map((s) => seconds(s.vanished_at_t) ?? seconds(s.last_seen_t)).filter((t): t is number => t !== null);
  const start = Math.min(...firsts);
  const finish = Math.max(...ends, start + 1);
  const range = finish - start;
  const bars: FlagBar[] = spans.map((span) => {
    const first = seconds(span.first_seen_t) ?? start;
    const vanished = seconds(span.vanished_at_t);
    const last = vanished ?? seconds(span.last_seen_t) ?? first;
    return {
      label: flagName(String(span.flag)).name,
      severity: String(span.severity),
      from: (first - start) / range,
      to: Math.max((last - start) / range, (first - start) / range + 0.02),
      ended: vanished !== null,
    };
  });
  // Flags that began late or ended early are the interesting ones, so they come first; the rest follow in the file's order.
  const odd = bars.filter((bar) => bar.from > 0.001 || bar.to < 0.999);
  const plain = bars.filter((bar) => !odd.includes(bar));
  const shown = [...odd, ...plain].slice(0, MAX_BARS);
  return {
    name: product.name,
    versions: Number(product.gold.mart_product_card?.[0]?.versions_kept ?? 0),
    startLabel: formatDay(dayOf(start)),
    endLabel: formatDay(dayOf(finish)),
    bars: shown,
    flagCount: spans.length,
  };
}

function checksOf(product: ShowcaseProduct): ChecksStory | null {
  const rows: CheckRow[] = (product.gold.product_rule_verdicts ?? [])
    .filter((row) => row.status === 'ok' || row.status === 'violated')
    .map((row) => ({ label: readableTag(String(row.rule)), ok: row.status === 'ok' }))
    .slice(0, 12);
  if (rows.length === 0) return null;
  const bad = rows.filter((row) => !row.ok).length;
  return { name: product.name, rows, ok: rows.length - bad, bad };
}

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

  const versions = (p: ShowcaseProduct) => Number(p.gold.mart_product_card?.[0]?.versions_kept ?? 0);
  const byHistory = [...showcase.products].sort((a, b) => versions(b) - versions(a));
  const history = byHistory.map(historyOf).find((h): h is HistoryStory => h !== null);
  const failures = (p: ShowcaseProduct) => (p.gold.product_rule_verdicts ?? []).filter((row) => row.status === 'violated').length;
  const byChecks = [...showcase.products].sort((a, b) => failures(b) - failures(a));
  const checks = byChecks.map(checksOf).find((c): c is ChecksStory => c !== null);
  if (!history || !checks) return null;

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
    history,
    checks,
  };
}
