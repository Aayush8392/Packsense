import { formatDay } from '../format';
import type { LineBound, LineField, PhotoLine } from './lines';

/** The owner's fixed public wording for the photo-read lines (A123), kept in one place and shown under every line. */
export const LINE_ACCURACY_NOTE = 'Photo-read lines: accuracy >= 96%. Lines are not checked by a person before they appear. Where the photo cannot be read, no line is shown.';

export const LINE_TITLE = 'Read from the product photo';

interface FieldWords {
  label: string;
  unit: string;
  /** Most decimal places shown. */
  places: number;
}

const FIELD_WORDS: Record<LineField, FieldWords> = {
  energy_kcal: { label: 'Energy', unit: 'kcal', places: 0 },
  energy_kj: { label: 'Energy', unit: 'kJ', places: 0 },
  fat: { label: 'Fat', unit: 'g', places: 2 },
  saturated_fat: { label: 'Saturated fat', unit: 'g', places: 2 },
  carbohydrates: { label: 'Carbohydrates', unit: 'g', places: 2 },
  sugars: { label: 'Sugars', unit: 'g', places: 2 },
  fiber: { label: 'Fibre', unit: 'g', places: 2 },
  proteins: { label: 'Protein', unit: 'g', places: 2 },
  salt: { label: 'Salt', unit: 'g', places: 3 },
  sodium: { label: 'Sodium', unit: 'g', places: 3 },
};

const ORDER = Object.keys(FIELD_WORDS) as LineField[];

/** A number with at most `places` decimals and no trailing zeros ("66.667" is "66.67" with two). */
export function shown(value: number, places: number): string {
  return String(Number(value.toFixed(places)));
}

export interface LineRow {
  label: string;
  text: string;
  /** Worked out from the partner value the pack prints (salt and sodium, kJ and kcal), not read directly. */
  worked: boolean;
}

/** The rows of the photo table, in a fixed order; a worked-out partner value is marked and never shown next to a value the photo gave itself. */
export function lineRows(line: PhotoLine): LineRow[] {
  const rows: LineRow[] = [];
  for (const field of ORDER) {
    const words = FIELD_WORDS[field];
    const own = line.values[field];
    const worked = line.derived[field];
    if (own !== undefined) rows.push({ label: words.label, text: `${shown(own, words.places)} ${words.unit}`, worked: false });
    else if (worked !== undefined) rows.push({ label: words.label, text: `${shown(worked, words.places)} ${words.unit}`, worked: true });
  }
  return rows;
}

export function basisText(basis: PhotoLine['basis']): string {
  return basis === 'per_100'
    ? 'The pack prints these values per 100 g or 100 ml.'
    : 'The pack prints these values per serving only. They are scaled to 100 g or 100 ml from the serving size printed on the pack.';
}

export function agreementText(lineType: PhotoLine['lineType']): string {
  return lineType === 'match'
    ? 'They agree with the values stored on Open Food Facts.'
    : 'They differ from the values stored on Open Food Facts.';
}

function boundText(b: LineBound): string {
  const stale = FIELD_WORDS[b.staleField];
  const confirmed = FIELD_WORDS[b.confirmedField];
  return `${stale.label} is stored as ${shown(b.stored, stale.places)} ${stale.unit}, but it can be ${b.kind} ${shown(b.confirmed, confirmed.places)} ${confirmed.unit}, because the photo confirms ${confirmed.label.toLowerCase()} at that value.`;
}

/** What the arithmetic checks say about these values. Short, factual, and never a verdict on the product. */
export function statementText(line: PhotoLine): string[] {
  switch (line.statement) {
    case 'repaired':
      return ['With these values, none of the PackSense arithmetic checks fail.'];
    case 'checked':
      return ['The stored values broke none of the PackSense arithmetic checks. The photo values are shown for comparison.'];
    case 'open':
      return ['A PackSense arithmetic check still fails with these values. Packs sometimes print numbers that do not add up.'];
    case 'bound':
      return line.bounds.map(boundText);
  }
}

export const lineReadOn = (line: PhotoLine) => `Read on ${formatDay(line.night)}`;
