import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { SHOWCASE_CODES, showcaseKeyFor } from './showcaseCodes';

describe('the four walk-through products', () => {
  it('match the showcase file, key and barcode', () => {
    const file = JSON.parse(readFileSync(join(import.meta.dirname, '..', '..', '..', 'showcase', 'showcase.json'), 'utf-8')) as { products: { key: string; code: string }[] };
    expect(Object.fromEntries(file.products.map((p) => [p.key, p.code]))).toEqual(SHOWCASE_CODES);
  });

  it('are found by barcode, with or without leading zeros, and nothing else is', () => {
    expect(showcaseKeyFor('8000500026731')).toBe('ordinary_food');
    expect(showcaseKeyFor('856312002795')).toBe('long_history');
    expect(showcaseKeyFor('0856312002795')).toBe('long_history');
    expect(showcaseKeyFor('8901719135171')).toBeNull();
  });
});
