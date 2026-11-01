/**
 * The four products of the walk-through on "How PackSense works", by the key that page uses in its address (?product=) and by barcode. The Look up page uses it to offer a link
 * to the walk-through for those four barcodes. A test keeps it equal to the showcase file.
 */
export const SHOWCASE_CODES: Record<string, string> = {
  ordinary_food: '8000500026731',
  several_flags: '4337256191760',
  long_history: '0856312002795',
  india: '8901719135170',
};

const stripZeros = (code: string) => code.replace(/^0+/, '');

/** The walk-through key of a barcode, or null when the barcode is not one of the four (leading zeros do not matter). */
export function showcaseKeyFor(code: string): string | null {
  const wanted = stripZeros(code);
  return Object.entries(SHOWCASE_CODES).find(([, known]) => stripZeros(known) === wanted)?.[0] ?? null;
}
