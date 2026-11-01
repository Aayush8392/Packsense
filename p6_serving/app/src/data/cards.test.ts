import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lookupCard, parseCardShard, parseSplits, resetCards } from './cards';

const fixture = (name: string) => readFileSync(join(import.meta.dirname, 'fixtures', name), 'utf-8');
const SHARD_8901 = fixture('cards_8901.fixture.csv');

function serve(files: Record<string, string | Response | Error>) {
  const asked: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    const name = String(url).split('/data/').pop() ?? '';
    asked.push(name);
    const found = files[name];
    if (found instanceof Error) throw found;
    if (found instanceof Response) return found;
    return found === undefined ? new Response('', { status: 404 }) : new Response(found, { status: 200 });
  });
  return asked;
}

beforeEach(resetCards);
afterEach(() => vi.unstubAllGlobals());

describe('reading card files', () => {
  it('reads every column of a card, with the flags as numbers and the two yes/no columns as booleans', () => {
    const card = parseCardShard(SHARD_8901).get('8901030383458');
    expect(card).toEqual({
      code: '8901030383458', existence: 'present_in_snapshot', light: 'one_flagged', thingsFlagged: 1, offError: 0, offBug: 0, offWarning: 3, offInfo: 5,
      rulesCheckable: 9, rulesFailed: 1, fieldsFilled: 6, versionsKept: 14, lastEditT: 1792000000, firstVersionEditedT: 1790000000, firstPeriodFromSeed: false, inIndia: true,
    });
  });

  it('refuses a value outside its domain, a missing column and a code that is not a barcode', () => {
    const lines = SHARD_8901.split('\n');
    const header = lines[0];
    const row = lines.find((line) => line.startsWith('8901030383458')) as string;
    expect(() => parseCardShard(`${header}\n${row.replace('one_flagged', 'fine')}\n`)).toThrow(/light outside its values/);
    expect(() => parseCardShard(`${header}\n${row.replace('present_in_snapshot', 'ok')}\n`)).toThrow(/existence_status outside/);
    expect(() => parseCardShard(`${header.replace('in_india', 'india')}\n${row}\n`)).toThrow(/missing the column in_india/);
    expect(() => parseCardShard(`${header}\n${row.replace(/^\d+/, '12ab')}\n`)).toThrow(/not a barcode/);
    expect(() => parseCardShard(`${header}\n${row.replace(',14,', ',-1,')}\n`)).toThrow(/versions_kept/);
  });

  it('reads the list of split prefixes and refuses anything else', () => {
    expect([...parseSplits('{"version":1,"splits":["890","8901"]}')]).toEqual(['890', '8901']);
    expect(() => parseSplits('not json')).toThrow();
    expect(() => parseSplits('{"splits":["89"]}')).toThrow(/no list/);
    expect(() => parseSplits('{}')).toThrow(/no list/);
  });
});

describe('looking a barcode up', () => {
  const SPLITS = '{"version":1,"splits":["890"]}';

  it('follows the split list to the right file and returns the card', async () => {
    const asked = serve({ 'cards/splits.json': SPLITS, 'cards/8901.csv': SHARD_8901 });
    const result = await lookupCard('8901030383458');
    expect(result.found && result.card.fieldsFilled).toBe(6);
    expect(asked).toEqual(['cards/splits.json', 'cards/8901.csv']);
  });

  it('reads a file once for several lookups, and the split list once', async () => {
    const asked = serve({ 'cards/splits.json': SPLITS, 'cards/8901.csv': SHARD_8901 });
    await lookupCard('8901030383458');
    await lookupCard('8901030383007');
    expect(asked).toEqual(['cards/splits.json', 'cards/8901.csv']);
  });

  it('finds a code typed without its leading zero by trying the padded forms', async () => {
    serve({ 'cards/splits.json': SPLITS, 'cards/004.csv': fixture('cards_004.fixture.csv') });
    const result = await lookupCard('44000015923');
    expect(result.found && result.card.code).toBe('0044000015923');
  });

  it('says not found, with what it tried, when no file has the code or a file does not exist', async () => {
    serve({ 'cards/splits.json': SPLITS, 'cards/8901.csv': SHARD_8901 });
    const missed = await lookupCard('8901030383999');
    expect(missed.found).toBe(false);
    expect(missed.found === false && missed.tried[0]).toBe('8901030383999');
    expect((await lookupCard('5000112637922')).found).toBe(false);
  });

  it('treats a home page answered for a missing file as no file', async () => {
    serve({ 'cards/splits.json': SPLITS, 'cards/500.csv': '<!doctype html><html></html>' });
    expect((await lookupCard('5000112637922')).found).toBe(false);
  });

  it('throws when the split list or a file cannot be loaded, and works again after a reset', async () => {
    serve({ 'cards/splits.json': new Error('offline') });
    await expect(lookupCard('8901030383458')).rejects.toThrow(/could not be reached/);
    serve({});
    await expect(lookupCard('8901030383458')).rejects.toThrow(/splits.json could not be loaded/);
    serve({ 'cards/splits.json': SPLITS, 'cards/8901.csv': new Response('', { status: 503 }) });
    await expect(lookupCard('8901030383458')).rejects.toThrow(/\(503\)/);
    serve({ 'cards/splits.json': SPLITS, 'cards/8901.csv': SHARD_8901 });
    expect((await lookupCard('8901030383458')).found).toBe(true);
  });
});
