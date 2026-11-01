import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { checkDigitOk, cleanTyped, hasBarcodeLength, shardFor, variants } from './barcode';

describe('typed barcodes', () => {
  it('drops spaces and hyphens and refuses anything else but digits', () => {
    expect(cleanTyped(' 8901 0303-83458 ')).toBe('8901030383458');
    expect(cleanTyped('8901030383458\n')).toBe('8901030383458');
    expect(cleanTyped('89010x03')).toBeNull();
    expect(cleanTyped('８９０１')).toBeNull();
    expect(cleanTyped('')).toBe('');
  });

  it('accepts 8 to 14 digits only', () => {
    expect(['1234567', '12345678', '12345678901234', '123456789012345'].map(hasBarcodeLength)).toEqual([false, true, true, false]);
  });
});

describe('the check digit', () => {
  it('passes real EAN-13, UPC-A, EAN-8 and GTIN-14 numbers', () => {
    for (const ok of ['4006381333931', '036000291452', '73513537', '96385074', '5000112637922', '10012345678902']) expect(checkDigitOk(ok), ok).toBe(true);
  });

  it('fails a wrong last digit, a swapped pair and every length that is not a barcode length', () => {
    for (const bad of ['4006381333932', '4006381333391', '036000291453', '73513538', '123456789', '1234567890', '12345678901']) expect(checkDigitOk(bad), bad).toBe(false);
  });
});

describe('the forms a number may be stored in', () => {
  it('tries what was typed first, then the number padded to the other barcode lengths', () => {
    expect(variants('036000291452')).toEqual(['036000291452', '0036000291452', '00036000291452']);
    expect(variants('0036000291452')).toEqual(['0036000291452', '036000291452', '00036000291452']);
    expect(variants('4006381333931')).toEqual(['4006381333931', '04006381333931']);
  });

  it('adds the missing leading zero of a UPC typed with eleven digits', () => {
    expect(variants('36000291452')).toEqual(['36000291452', '0036000291452', '036000291452', '00036000291452']);
  });

  it('keeps an EAN-8 and its padded forms, and never offers more than five forms', () => {
    expect(variants('73513537')).toEqual(['73513537', '0000073513537', '000073513537', '00000073513537']);
    for (const typed of ['73513537', '36000291452', '0000000012345', '12345678901234']) expect(variants(typed).length).toBeLessThanOrEqual(5);
  });
});

describe('the lookup rule against the Python rule', () => {
  const vectors = JSON.parse(readFileSync(join(import.meta.dirname, '..', 'data', 'fixtures', 'shard_vectors.json'), 'utf-8')) as { code: string; splits: string[]; shard: string }[];

  it('names the same file as licence_gate.shard_for for every vector', () => {
    expect(vectors.length).toBeGreaterThan(200);
    for (const v of vectors) expect(shardFor(v.code, new Set(v.splits)), `${v.code} ${v.splits.join(',')}`).toBe(v.shard);
  });
});
