import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCards } from './cards';
import { agreementText, basisText, lineRows, shown, statementText } from './lineWords';
import { lookupLine, parseLineShard, resetLines } from './lines';

const LINE = {
  code: '8901071732857', night: '2026-11-14', line_type: 'match', statement: 'checked', basis: 'per_serving_converted',
  values: { carbohydrates: 66.666667, energy_kcal: 276.666667, fat: 0.666667, proteins: 1.333333, saturated_fat: 0.5, sodium: 0.073333, sugars: 63.666667 },
  derived: { energy_kj: 1157.5733 }, bounds: [],
};
const shardText = (lines: unknown[]) => JSON.stringify({ version: 1, lines });

function serve(files: Record<string, string | Error>) {
  const asked: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    const name = String(url).split('/data/').pop() ?? '';
    asked.push(name);
    const found = files[name];
    if (found instanceof Error) throw found;
    return found === undefined ? new Response('', { status: 404 }) : new Response(found, { status: 200 });
  });
  return asked;
}

beforeEach(() => {
  resetCards();
  resetLines();
});
afterEach(() => vi.unstubAllGlobals());

describe('reading line files', () => {
  it('reads a line with its numbers and its words', () => {
    const line = parseLineShard(shardText([LINE])).get('8901071732857');
    expect(line).toMatchObject({ lineType: 'match', statement: 'checked', basis: 'per_serving_converted', bounds: [] });
    expect(line?.values.energy_kcal).toBeCloseTo(276.67, 2);
    expect(line?.derived.energy_kj).toBeCloseTo(1157.57, 2);
  });

  it.each([
    ['a basis outside its values', { ...LINE, basis: 'per piece' }, /basis outside/],
    ['a statement outside its values', { ...LINE, statement: 'great' }, /statement outside/],
    ['a field that is not allowed', { ...LINE, values: { ...LINE.values, colour: 1 } }, /field outside/],
    ['a value out of range', { ...LINE, values: { ...LINE.values, fat: -1 } }, /out of range/],
    ['a code that is not a barcode', { ...LINE, code: '12' }, /not a barcode/],
    ['a night that is not a date', { ...LINE, night: 'yesterday' }, /not a date/],
  ])('refuses %s and stops the whole file', (_name, bad, message) => {
    expect(() => parseLineShard(shardText([LINE, bad]))).toThrow(message);
  });

  it('refuses a file that is not a version 1 list', () => {
    expect(() => parseLineShard('{"version":2,"lines":[]}')).toThrow(/no list of lines/);
    expect(() => parseLineShard('not json')).toThrow(/not valid/);
  });
});

describe('looking a line up', () => {
  const SPLITS = JSON.stringify({ version: 1, splits: ['890'] });

  it('finds the line in the file the lookup rule names', async () => {
    const asked = serve({ 'cards/splits.json': SPLITS, 'lines/8901.json': shardText([LINE]) });
    expect((await lookupLine('8901071732857'))?.basis).toBe('per_serving_converted');
    expect(asked).toContain('lines/8901.json');
  });

  it('gives null for a product with no line, with no lines file, and for any failure', async () => {
    serve({ 'cards/splits.json': SPLITS, 'lines/8901.json': shardText([LINE]) });
    expect(await lookupLine('8901030383458')).toBeNull();
    resetLines();
    serve({ 'cards/splits.json': SPLITS });
    expect(await lookupLine('8901071732857')).toBeNull();
    resetLines();
    resetCards();
    serve({ 'cards/splits.json': SPLITS, 'lines/8901.json': 'not json' });
    expect(await lookupLine('8901071732857')).toBeNull();
    resetLines();
    resetCards();
    serve({ 'cards/splits.json': new Error('offline') });
    expect(await lookupLine('8901071732857')).toBeNull();
  });
});

describe('the words of a line', () => {
  const line = parseLineShard(shardText([LINE])).get('8901071732857')!;

  it('shows the photo table in a fixed order with sensible rounding and marks worked-out values', () => {
    const rows = lineRows(line);
    expect(rows.map((r) => r.label)).toEqual(['Energy', 'Energy', 'Fat', 'Saturated fat', 'Carbohydrates', 'Sugars', 'Protein', 'Sodium']);
    expect(rows[0]).toEqual({ label: 'Energy', text: '277 kcal', worked: false });
    expect(rows[1]).toEqual({ label: 'Energy', text: '1158 kJ', worked: true });
    expect(rows.find((r) => r.label === 'Carbohydrates')?.text).toBe('66.67 g');
    expect(rows.find((r) => r.label === 'Sodium')?.text).toBe('0.073 g');
  });

  it('says when the values were scaled from a serving, and whether they agree with the stored ones', () => {
    expect(basisText(line.basis)).toMatch(/per serving only/);
    expect(basisText('per_100')).toMatch(/per 100 g or 100 ml\.$/);
    expect(agreementText('match')).toMatch(/agree/);
    expect(agreementText('differ')).toMatch(/differ/);
  });

  it('has one fixed sentence per statement, and one per bound', () => {
    expect(statementText(line)).toHaveLength(1);
    const bound = { ...line, statement: 'bound' as const, bounds: [{ rule: 'saturated-fat-greater-than-fat' as const, staleField: 'saturated_fat' as const, stored: 12, confirmedField: 'fat' as const, confirmed: 9.5, kind: 'at most' as const }] };
    expect(statementText(bound)).toEqual(['Saturated fat is stored as 12 g, but it can be at most 9.5 g, because the photo confirms fat at that value.']);
    expect(statementText({ ...line, statement: 'open' })[0]).toMatch(/still fails/);
    expect(statementText({ ...line, statement: 'repaired' })[0]).toMatch(/none of the PackSense arithmetic checks fail/);
  });

  it('rounds without trailing zeros', () => {
    expect(shown(66.666667, 2)).toBe('66.67');
    expect(shown(0.5, 2)).toBe('0.5');
    expect(shown(12, 2)).toBe('12');
  });
});
