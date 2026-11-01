import { shardFor, variants } from '../lookup/barcode';
import { parseCsv } from './csv';
import { DataError, dataUrl } from './siteData';

export const EXISTENCE_STATUSES = [
  'unverified', 'present_in_snapshot', 'confirmed_exists', 'confirmed_not_found', 'moved_other_type', 'invalid_code', 'unconfirmed',
] as const;
export type ExistenceStatus = (typeof EXISTENCE_STATUSES)[number];

export const LIGHTS = ['several_flagged', 'one_flagged', 'none_flagged', 'not_enough_data'] as const;
export type Light = (typeof LIGHTS)[number];

/** One product's card: derived facts only, as published in `cards/<prefix>.csv`. */
export interface Card {
  code: string;
  existence: ExistenceStatus;
  light: Light;
  /** OFF's error and bug flags plus PackSense's failed rules (warnings and information flags are not counted). */
  thingsFlagged: number;
  offError: number;
  offBug: number;
  offWarning: number;
  offInfo: number;
  /** Of PackSense's 11 arithmetic checks: how many could be run on this product, and how many of those failed. */
  rulesCheckable: number;
  rulesFailed: number;
  /** How many of the seven key fields are filled. */
  fieldsFilled: number;
  versionsKept: number;
  /** Seconds since 1970 (UTC): the latest edit held, and the Open Food Facts edit time of the first version held. */
  lastEditT: number;
  firstVersionEditedT: number;
  /** The first version held came with the bulk seed, so it is not the product's first version on Open Food Facts. */
  firstPeriodFromSeed: boolean;
  inIndia: boolean;
}

const COLUMNS = [
  'code', 'existence_status', 'light', 'things_flagged', 'off_error', 'off_bug', 'off_warning', 'off_info', 'rules_checkable', 'rules_failed',
  'fields_filled', 'versions_kept', 'last_edit_t', 'first_version_edited_t', 'first_period_from_seed', 'in_india',
];

function whole(text: string, column: string): number {
  const value = Number(text);
  if (text.trim() === '' || !Number.isInteger(value) || value < 0) throw new DataError(`A card file has a ${column} that is not a whole number: '${text}'`);
  return value;
}

function oneOf<T extends string>(text: string, allowed: readonly T[], column: string): T {
  if (!(allowed as readonly string[]).includes(text)) throw new DataError(`A card file has a ${column} outside its values: '${text}'`);
  return text as T;
}

/** The rows of one card file by barcode. A value outside its domain stops the whole file: a card must never show a meaning it was not given. */
export function parseCardShard(text: string): Map<string, Card> {
  const rows = parseCsv(text);
  const cards = new Map<string, Card>();
  if (rows.length === 0) return cards;
  const missing = COLUMNS.filter((name) => !(name in rows[0]));
  if (missing.length > 0) throw new DataError(`A card file is missing the column ${missing.join(', ')}`);
  for (const row of rows) {
    if (!/^\d{8,14}$/.test(row.code)) throw new DataError(`A card file has a code that is not a barcode: '${row.code}'`);
    cards.set(row.code, {
      code: row.code,
      existence: oneOf(row.existence_status, EXISTENCE_STATUSES, 'existence_status'),
      light: oneOf(row.light, LIGHTS, 'light'),
      thingsFlagged: whole(row.things_flagged, 'things_flagged'),
      offError: whole(row.off_error, 'off_error'),
      offBug: whole(row.off_bug, 'off_bug'),
      offWarning: whole(row.off_warning, 'off_warning'),
      offInfo: whole(row.off_info, 'off_info'),
      rulesCheckable: whole(row.rules_checkable, 'rules_checkable'),
      rulesFailed: whole(row.rules_failed, 'rules_failed'),
      fieldsFilled: whole(row.fields_filled, 'fields_filled'),
      versionsKept: whole(row.versions_kept, 'versions_kept'),
      lastEditT: whole(row.last_edit_t, 'last_edit_t'),
      firstVersionEditedT: whole(row.first_version_edited_t, 'first_version_edited_t'),
      firstPeriodFromSeed: row.first_period_from_seed === '1',
      inIndia: row.in_india === '1',
    });
  }
  return cards;
}

export function parseSplits(text: string): Set<string> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new DataError('cards/splits.json is not valid');
  }
  const list = (parsed as { splits?: unknown }).splits;
  if (!Array.isArray(list) || !list.every((p) => typeof p === 'string' && /^\d{3,6}$/.test(p))) throw new DataError('cards/splits.json has no list of prefixes');
  return new Set(list as string[]);
}

/** Text of one published file; null when the site has no such file (a missing card file means "not in our copy"). */
async function fetchOptional(name: string): Promise<string | null> {
  let response: Response;
  try {
    response = await fetch(dataUrl(name));
  } catch {
    throw new DataError(`${name} could not be reached`);
  }
  if (response.status === 404) return null;
  if (!response.ok) throw new DataError(`${name} could not be loaded (${response.status})`);
  const text = await response.text();
  // A server that answers an unknown file with its home page has no such file.
  return /^\s*</.test(text) ? null : text;
}

let splitsLoad: Promise<Set<string>> | null = null;
const shardLoads = new Map<string, Promise<Map<string, Card> | null>>();

/** Forgets what was fetched (used by tests and by the retry button after an error). */
export function resetCards(): void {
  splitsLoad = null;
  shardLoads.clear();
}

function splits(): Promise<Set<string>> {
  if (!splitsLoad) {
    splitsLoad = (async () => {
      const text = await fetchOptional('cards/splits.json');
      if (text === null) throw new DataError('cards/splits.json could not be loaded');
      return parseSplits(text);
    })();
    splitsLoad.catch(() => {
      splitsLoad = null;
    });
  }
  return splitsLoad;
}

function shard(prefix: string): Promise<Map<string, Card> | null> {
  let load = shardLoads.get(prefix);
  if (!load) {
    load = (async () => {
      const text = await fetchOptional(`cards/${prefix}.csv`);
      return text === null ? null : parseCardShard(text);
    })();
    load.catch(() => shardLoads.delete(prefix));
    shardLoads.set(prefix, load);
  }
  return load;
}

export type Lookup = { found: true; card: Card } | { found: false; tried: string[] };

/**
 * Looks a barcode up in the published cards: for each form it may be stored in, take the file the lookup rule names and look for the code in it.
 * Throws a DataError when a file cannot be fetched or read; a file that does not exist is an ordinary "not in our copy".
 */
export async function lookupCard(digits: string): Promise<Lookup> {
  const prefixes = await splits();
  const tried: string[] = [];
  for (const form of variants(digits)) {
    tried.push(form);
    const cards = await shard(shardFor(form, prefixes));
    const card = cards?.get(form);
    if (card) return { found: true, card };
  }
  return { found: false, tried };
}
