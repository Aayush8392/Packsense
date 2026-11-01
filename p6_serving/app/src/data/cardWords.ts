import { pageBySlug } from '../content';
import { formatDay } from '../format';
import type { Card, ExistenceStatus, Light } from './cards';

export interface SignalWords {
  label: string;
  line: string;
}

/** The four words and the line under each, written in the page text (content/10-barcode-lookup.md); the data holds only the neutral codes. */
export function signalWords(light: Light): SignalWords {
  const found = pageBySlug('barcode-lookup')?.meta.signal_labels?.[light];
  if (!found) throw new Error(`The Look up page text has no signal words for '${light}'`);
  return found;
}

export interface StatusNotice {
  title: string;
  body: string;
  /** True when the signal must not be shown as normal under it (the product is gone or moved). */
  replacesSignal: boolean;
}

const NOTICES: Partial<Record<ExistenceStatus, StatusNotice>> = {
  confirmed_not_found: {
    title: 'Moved or removed on Open Food Facts',
    body: 'Open Food Facts no longer shows this product at this barcode: it was moved to another Open Food Facts database or removed. The facts below come from the versions PackSense kept before that.',
    replacesSignal: true,
  },
  moved_other_type: {
    title: 'Moved or removed on Open Food Facts',
    body: 'Open Food Facts no longer shows this product at this barcode: it was moved to another Open Food Facts database or removed. The facts below come from the versions PackSense kept before that.',
    replacesSignal: true,
  },
  invalid_code: {
    title: 'Not a valid barcode',
    body: 'This number does not pass the barcode check, so it was not confirmed on Open Food Facts. The facts below are what PackSense holds under it.',
    replacesSignal: false,
  },
};

export function statusNotice(status: ExistenceStatus): StatusNotice | null {
  return NOTICES[status] ?? null;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Open Food Facts' flags by severity. Errors and bugs are shown together as errors, the way the signal counts them. */
export function offFlagsText(card: Card): string {
  return `${plural(card.offError + card.offBug, 'error', 'errors')} · ${plural(card.offWarning, 'warning', 'warnings')} · ${card.offInfo} information`;
}

export const OFF_FLAGS_NOTE = 'Only errors count toward the signal; warnings and information flags are shown but not counted.';

/** How many of PackSense's 11 arithmetic checks failed, and how many could not be run on this product. */
export function rulesText(card: Card): string {
  if (card.rulesCheckable === 0) return 'None could be run: there is no nutrition table to check';
  const unrunnable = 11 - card.rulesCheckable;
  return `${card.rulesFailed} of ${card.rulesCheckable} failed${unrunnable > 0 ? ` (${plural(unrunnable, 'check', 'checks')} could not be run)` : ''}`;
}

export const keyFieldsText = (card: Card) => `${card.fieldsFilled} of 7 filled`;

export const versionsText = (card: Card) => `${plural(card.versionsKept, 'version', 'versions')} kept`;

export function dayOfEpoch(seconds: number): string {
  return formatDay(new Date(seconds * 1000).toISOString());
}

export function datesText(card: Card): string {
  return `First version held: ${dayOfEpoch(card.firstVersionEditedT)} · Last edit: ${dayOfEpoch(card.lastEditT)}`;
}

export const SEED_NOTE = 'The first version held came with the starting copy, so earlier edits on Open Food Facts are not held.';

export const offLink = (code: string) => `https://world.openfoodfacts.org/product/${code}`;

export const CARD_DISCLAIMER = 'This card is a factual summary of stored checks. It never says a product is right, wrong, safe, or good.';
