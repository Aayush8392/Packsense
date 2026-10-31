/**
 * The four words of a product's signal and the line under each, as decided for the product card (page text 10-barcode-lookup.md). The data holds only the code; the words belong to the app.
 * A flag means "worth a look", never "wrong"; the signal never says a product is right or wrong.
 */
export const SIGNALS: Record<string, { label: string; line: string }> = {
  several_flagged: {
    label: 'Several things flagged',
    line: "Flagged by Open Food Facts' own checks or by PackSense's 11 arithmetic checks. A flag means worth a look, not wrong.",
  },
  one_flagged: {
    label: 'One thing flagged',
    line: "Flagged by Open Food Facts' own checks or by PackSense's 11 arithmetic checks. A flag means worth a look, not wrong.",
  },
  none_flagged: {
    label: 'Nothing flagged',
    line: "Open Food Facts' own checks and PackSense's 11 arithmetic checks found nothing. This does not mean the entry is correct.",
  },
  not_enough_data: {
    label: 'Not enough data to check',
    line: 'The checks could not be run because there is no nutrition table to check.',
  },
};

export function signalFor(code: string): { label: string; line: string } {
  return SIGNALS[code] ?? { label: code, line: '' };
}
