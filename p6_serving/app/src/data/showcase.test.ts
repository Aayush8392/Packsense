import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  GOLD_TABLES, GOLD_VIEWS, doneRows, goldCell, parseShowcase, rawEnergy, rawRows, reasonFor, sameFieldRows, searchRows, silverRows,
} from './showcase';
import { DataError } from './siteData';

// The committed showcase file itself: four real products (Kinder Surprise, Farmer Salat, Fairlife chocolate milk, Parle Monaco), made on 23 Oct 2026.
const text = readFileSync(join(import.meta.dirname, '..', '..', '..', 'showcase', 'showcase.json'), 'utf-8');
const data = parseShowcase(text);
const byKey = (key: string) => data.products.find((p) => p.key === key)!;

describe('the showcase file', () => {
  it('holds four products, the markers and 76 stand-in names', () => {
    expect(data.products.map((p) => p.key)).toEqual(['ordinary_food', 'several_flags', 'long_history', 'india']);
    expect(data.markers).toEqual({ images: '[images removed]', hidden: 'hidden on purpose' });
    expect(data.standIns).toHaveLength(76);
    expect(data.standIns[0]).toBe('contributor-A');
    expect(data.builtAt).toBe('2026-10-23T19:45:29');
  });

  it('refuses a file that is not readable, is not version 1, has no products, or lacks a gold table', () => {
    expect(() => parseShowcase('not json')).toThrow(DataError);
    expect(() => parseShowcase(JSON.stringify({ ...JSON.parse(text), version: 2 }))).toThrow(/version 1/);
    expect(() => parseShowcase(JSON.stringify({ ...JSON.parse(text), products: [] }))).toThrow(/no products/);
    const broken = JSON.parse(text);
    delete broken.products[0].gold.product_history;
    expect(() => parseShowcase(JSON.stringify(broken))).toThrow(/missing the table product_history/);
  });

  it('gives every product all eight gold tables', () => {
    for (const product of data.products) for (const table of GOLD_TABLES) expect(Array.isArray(product.gold[table]), `${product.key} ${table}`).toBe(true);
  });
});

describe('the raw and cleaned lists', () => {
  it('lists every raw field in file order (245 for the first product), and marks exactly the image fields the export recorded', () => {
    const kinder = byKey('ordinary_food');
    const rows = rawRows(kinder, data.markers);
    expect(rows).toHaveLength(245);
    expect(rows[0].key).toBe('_id');
    for (const product of data.products) {
      const marked = rawRows(product, data.markers).filter((r) => r.hidden).length;
      expect(marked, product.key).toBe(product.bronze.counts.image_fields_marked);
    }
  });

  it('lists the 81 cleaned columns of every product and marks exactly the hidden ones the export recorded (17)', () => {
    for (const product of data.products) {
      const rows = silverRows(product, data.markers);
      expect(rows).toHaveLength(81);
      expect(rows.filter((r) => r.hidden)).toHaveLength(17);
      expect(rows.filter((r) => r.hidden).length).toBe(product.silver.counts.silver_columns_hidden);
      expect(rows.filter((r) => r.hidden).every((r) => r.key.endsWith('_hmac') || /key_version|source_file|file_sha256|_at$|contract_version|job_run_id/.test(r.key))).toBe(true);
    }
  });

  it('cuts a long value and keeps the whole text to open on demand, and writes a null as a dash', () => {
    const rows = rawRows(byKey('india'), data.markers);
    const long = rows.find((r) => r.full !== null)!;
    expect(long.short.endsWith('…')).toBe(true);
    expect(long.full!.length).toBeGreaterThan(long.short.length);
    expect(silverRows(byKey('india'), data.markers).find((r) => r.key === 'labels_tags')?.short).toBe('[]');
  });

  it('searches keys and values without caring about case', () => {
    const rows = silverRows(byKey('india'), data.markers);
    const hits = searchRows(rows, 'ENERGY');
    expect(hits.map((r) => r.key)).toEqual(expect.arrayContaining(['energy_kj', 'energy_kcal']));
    expect(searchRows(rows, 'parle monaco').some((r) => r.key === 'product_name')).toBe(true);
    expect(searchRows(rows, 'zzzz-nothing')).toEqual([]);
    expect(searchRows(rows, '  ')).toHaveLength(81);
  });
});

describe('the same field, three steps', () => {
  it('reads the packaging energy per 100 g from the raw nutrition sets, and says how many sets the record holds', () => {
    expect(rawEnergy(byKey('ordinary_food').bronze.record)).toBe('energy-kcal "561" in the packaging set per 100g; the record holds 3 separate sets');
    expect(rawEnergy(byKey('several_flags').bronze.record)).toContain('"75"');
    expect(rawEnergy({})).toBe('—');
  });

  it('shows the real values of each step for the Indian product', () => {
    const rows = sameFieldRows(byKey('india'));
    expect(rows.map((r) => r.field)).toEqual(['Name', 'Pack size', 'Categories', 'Energy per 100 g']);
    expect(rows[0]).toMatchObject({ raw: 'product_name: parle monaco 700g', silver: 'product_name: parle monaco 700g' });
    expect(rows[1].raw).toBe('quantity: 696 g (43.5g * 16 units) (one text)');
    expect(rows[1].silver).toContain('quantity_amount: 696');
    expect(rows[1].silver).toContain('quantity_unit: g');
    expect(rows[3].raw).toContain('"492"');
    expect(rows[3].silver).toContain('492');
    expect(rows[3].gold).toContain('energy_kcal: 492');
  });

  it('uses the newest version of a product with a long history', () => {
    const milk = byKey('long_history');
    expect(milk.gold.product_history).toHaveLength(18);
    const rows = sameFieldRows(milk);
    expect(rows[3].gold).toContain('energy_kcal: 140');
  });
});

describe('the gold tables', () => {
  it('has a view for each of the eight tables, and every column it shows exists in the real rows of every product', () => {
    expect(GOLD_VIEWS.map((v) => v.table)).toEqual([...GOLD_TABLES]);
    for (const view of GOLD_VIEWS) {
      for (const product of data.products) {
        const first = product.gold[view.table][0];
        expect(first, `${product.key} ${view.table}`).toBeDefined();
        for (const column of view.columns) expect(column.key in first, `${view.table}.${column.key}`).toBe(true);
      }
    }
  });

  it('writes a cell as plain text: days, counts, yes and no, flag names, signal words, and a dash for nothing', () => {
    expect(goldCell(1791734043, 'date')).toBe('11 Oct 2026');
    expect(goldCell('2026-10-02T17:30:01', 'date')).toBe('2 Oct 2026');
    expect(goldCell(96907, 'count')).toBe('96,907');
    expect(goldCell(1, 'yesno')).toBe('yes');
    expect(goldCell(false, 'yesno')).toBe('no');
    expect(goldCell('en:environmental-score-quality-warnings', 'flag')).toBe('Environmental score quality warnings');
    expect(goldCell('none_flagged', 'signal')).toBe('Nothing flagged');
    expect(goldCell(null, undefined)).toBe('—');
    expect(goldCell(2.2275, 'number')).toBe('2.2275');
  });

  it('shows a signal of four words and the counts for each product card, as the card page will', () => {
    const light = (key: string) => byKey(key).gold.mart_product_card[0].light;
    expect(light('several_flags')).toBe('several_flagged');
    expect(goldCell(light('several_flags'), 'signal')).toBe('Several things flagged');
    expect(goldCell(light('ordinary_food'), 'signal')).toBe('Nothing flagged');
  });
});

describe('what was removed or replaced', () => {
  it("lists the real counts of the first product: 102 contributor fields, 6 names in text, 1 image field, 17 hidden columns", () => {
    const rows = doneRows(byKey('ordinary_food'));
    expect(rows.map((r) => r.count)).toEqual([102, 6, 0, 1, 0, 17, 0]);
    expect(rows[0].text).toContain('contributor-A');
  });

  it('shows the product with a renamed key and removed patterns (the long history one)', () => {
    const rows = doneRows(byKey('long_history'));
    expect(rows.find((r) => r.text.includes('renamed'))?.count).toBe(1);
    expect(rows.find((r) => r.text.includes('email'))?.count).toBe(3);
  });

  it('says why each product was picked, with the real number of versions for the long history one', () => {
    expect(reasonFor(byKey('long_history'))).toBe('A long edit history: 18 versions kept.');
    expect(reasonFor(byKey('india'))).toBe('A product from India.');
  });
});
