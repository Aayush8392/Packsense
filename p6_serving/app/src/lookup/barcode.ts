/** What a visitor typed, cleaned to digits; null when anything but digits, spaces and hyphens is in it. */
export function cleanTyped(text: string): string | null {
  const stripped = text.replace(/[\s-]+/g, '');
  return /^\d*$/.test(stripped) ? stripped : null;
}

/** The published cards are barcodes of 8 to 14 digits, so nothing else is looked up. */
export function hasBarcodeLength(digits: string): boolean {
  return digits.length >= 8 && digits.length <= 14;
}

/**
 * The GS1 check digit: the last digit makes the weighted sum (3 and 1 alternating from the right of the digits before it) a multiple of ten.
 * It is defined for the four barcode lengths EAN-8, UPC-A (12), EAN-13 and GTIN-14; any other length fails.
 */
export function checkDigitOk(digits: string): boolean {
  if (![8, 12, 13, 14].includes(digits.length) || !/^\d+$/.test(digits)) return false;
  const body = digits.slice(0, -1);
  let sum = 0;
  for (let i = 0; i < body.length; i += 1) {
    const fromRight = body.length - 1 - i;
    sum += Number(body[i]) * (fromRight % 2 === 0 ? 3 : 1);
  }
  return (10 - (sum % 10)) % 10 === Number(digits[digits.length - 1]);
}

const PADDED_LENGTHS = [13, 12, 14, 8];

/**
 * The forms of one number that may be stored: as typed first, then the number padded with leading zeros to the other barcode lengths. A UPC-A is kept by Open Food Facts
 * as 13 digits with a zero in front, and a code typed without its leading zero is the same number. At most four forms, so a lookup fetches at most four files.
 */
export function variants(digits: string): string[] {
  const number = digits.replace(/^0+/, '') || '0';
  const forms = [digits];
  for (const length of PADDED_LENGTHS) {
    if (number.length <= length) forms.push(number.padStart(length, '0'));
  }
  return [...new Set(forms)].filter(hasBarcodeLength);
}

/**
 * The lookup rule, written out as in `licence_gate.shard_for`: take the first 3 digits; while that prefix is in the list of split prefixes, take one more digit.
 * The result names the file `cards/<result>.csv`.
 */
export function shardFor(code: string, splits: ReadonlySet<string>): string {
  let prefix = code.slice(0, 3);
  while (splits.has(prefix) && prefix.length < code.length) prefix = code.slice(0, prefix.length + 1);
  return prefix;
}
