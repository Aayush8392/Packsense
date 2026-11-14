import { shardFor } from '../lookup/barcode';
import { fetchOptional, splits } from './cards';
import { DataError } from './siteData';

/** The nutrition fields a photo-read line may hold, in the order they are shown. */
export const LINE_FIELDS = ['energy_kcal', 'energy_kj', 'fat', 'saturated_fat', 'carbohydrates', 'sugars', 'fiber', 'proteins', 'salt', 'sodium'] as const;
export type LineField = (typeof LINE_FIELDS)[number];

export const LINE_TYPES = ['match', 'differ'] as const;
export const LINE_STATEMENTS = ['repaired', 'bound', 'open', 'checked'] as const;
export const LINE_BASES = ['per_100', 'per_serving_converted'] as const;
export const BOUND_RULES = ['saturated-fat-greater-than-fat', 'sugars-plus-starch-greater-than-carbohydrates'] as const;
export const BOUND_KINDS = ['at most', 'at least'] as const;

export interface LineBound {
  rule: (typeof BOUND_RULES)[number];
  staleField: LineField;
  stored: number;
  confirmedField: LineField;
  confirmed: number;
  kind: (typeof BOUND_KINDS)[number];
}

/** One photo-read line, as published in `lines/<prefix>.json`: numbers and words from fixed lists, never free text. */
export interface PhotoLine {
  code: string;
  night: string;
  lineType: (typeof LINE_TYPES)[number];
  statement: (typeof LINE_STATEMENTS)[number];
  basis: (typeof LINE_BASES)[number];
  /** The photo table per 100 g or 100 ml. */
  values: Partial<Record<LineField, number>>;
  /** Partner values worked out from a printed one (salt and sodium, kJ and kcal). */
  derived: Partial<Record<LineField, number>>;
  bounds: LineBound[];
}

const MAX_VALUE = 100000;

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) throw new DataError(`A lines file has a ${what} outside its values`);
  return value as T;
}

function numberIn(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > MAX_VALUE) throw new DataError(`A lines file has a ${what} out of range`);
  return value;
}

function table(value: unknown, what: string): Partial<Record<LineField, number>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new DataError(`A lines file has ${what} that is not an object`);
  const out: Partial<Record<LineField, number>> = {};
  for (const [name, v] of Object.entries(value)) {
    const field = oneOf(name, LINE_FIELDS, `${what} field`);
    out[field] = numberIn(v, what);
  }
  return out;
}

function parseBound(raw: unknown): LineBound {
  const b = raw as Record<string, unknown> | null;
  if (typeof b !== 'object' || b === null) throw new DataError('A lines file has a bound that is not an object');
  return {
    rule: oneOf(b.rule, BOUND_RULES, 'bound rule'),
    staleField: oneOf(b.stale_field, LINE_FIELDS, 'bound field'),
    stored: numberIn(b.stored, 'bound value'),
    confirmedField: oneOf(b.confirmed_field, LINE_FIELDS, 'bound field'),
    confirmed: numberIn(b.confirmed, 'bound value'),
    kind: oneOf(b.kind, BOUND_KINDS, 'bound kind'),
  };
}

/** The lines of one shard by barcode. A value outside its domain stops the whole file: a line must never show a meaning it was not given. */
export function parseLineShard(text: string): Map<string, PhotoLine> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new DataError('A lines file is not valid');
  }
  const doc = parsed as { version?: unknown; lines?: unknown };
  if (doc.version !== 1 || !Array.isArray(doc.lines)) throw new DataError('A lines file has no list of lines');
  const out = new Map<string, PhotoLine>();
  for (const raw of doc.lines as Record<string, unknown>[]) {
    if (typeof raw.code !== 'string' || !/^\d{8,14}$/.test(raw.code)) throw new DataError('A lines file has a code that is not a barcode');
    if (typeof raw.night !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(raw.night)) throw new DataError('A lines file has a night that is not a date');
    if (!Array.isArray(raw.bounds)) throw new DataError('A lines file has bounds that are not a list');
    out.set(raw.code, {
      code: raw.code,
      night: raw.night,
      lineType: oneOf(raw.line_type, LINE_TYPES, 'line_type'),
      statement: oneOf(raw.statement, LINE_STATEMENTS, 'statement'),
      basis: oneOf(raw.basis, LINE_BASES, 'basis'),
      values: table(raw.values, 'a value'),
      derived: table(raw.derived, 'a derived value'),
      bounds: raw.bounds.map(parseBound),
    });
  }
  return out;
}

const shardLoads = new Map<string, Promise<Map<string, PhotoLine> | null>>();

/** Forgets what was fetched (used by tests and by the retry button after an error). */
export function resetLines(): void {
  shardLoads.clear();
}

function shard(prefix: string): Promise<Map<string, PhotoLine> | null> {
  let load = shardLoads.get(prefix);
  if (!load) {
    load = (async () => {
      const text = await fetchOptional(`lines/${prefix}.json`);
      return text === null ? null : parseLineShard(text);
    })();
    load.catch(() => shardLoads.delete(prefix));
    shardLoads.set(prefix, load);
  }
  return load;
}

/**
 * The photo-read line of a stored barcode (a card's own code), or null. It uses the same lookup rule as the cards. Any problem (no such file, a file that cannot be read) ends in null: a line is a
 * bonus on a card, and when it cannot be shown without doubt, no line is shown.
 */
export async function lookupLine(code: string): Promise<PhotoLine | null> {
  try {
    const prefixes = await splits();
    // The card's own code is the stored form of the number, and the lines are filed under that same form.
    const line = (await shard(shardFor(code, prefixes)))?.get(code);
    if (line) return line;
  } catch {
    return null;
  }
  return null;
}
