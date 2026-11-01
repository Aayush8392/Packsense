// The loader against a stand-in server and cache:  node --test shrunk_loader.test.mjs   (from this folder). Needs the generated files (skipped without them).
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { FILES, makeBundle } from './make_bot_bundle.mjs';
import { loadBundle, shouldLoad } from './shrunk_loader.mjs';
import { createShrunkBot } from './shrunk_bot.mjs';

const ready = Object.values(FILES).every((f) => existsSync(new URL(f, import.meta.url)));
const skip = ready ? false : 'generated files are missing';
const out = ready ? mkdtempSync(join(tmpdir(), 'packsense-bot-')) : null;
after(() => out && rmSync(out, { recursive: true, force: true }));
const manifest = ready ? makeBundle(out) : null;

function server(overrides = {}) {
  const log = [];
  const fetchImpl = async (url) => {
    const name = url.split('/').pop();
    log.push(name);
    if (overrides[name]) return overrides[name]();
    const path = join(out, name);
    return existsSync(path) ? new Response(readFileSync(path)) : new Response('missing', { status: 404 });
  };
  return { fetchImpl, log };
}

function fakeCaches() {
  const stores = new Map();
  return {
    stores,
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return { match: async (url) => (store.has(url) ? new Response(store.get(url)) : undefined), put: async (url, response) => { store.set(url, new Uint8Array(await response.arrayBuffer())); } };
    },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
  };
}

test('the bundle is cut into chunks of at most 2 MB, each with a hash', { skip }, () => {
  assert.ok(manifest.totalBytes > 14e6 && manifest.totalBytes < 16e6, `total ${manifest.totalBytes}`);
  for (const f of Object.values(manifest.files)) for (const c of f.chunks) assert.ok(c.bytes <= manifest.chunkBytes && /^[0-9a-f]{64}$/.test(c.sha256));
  assert.equal(manifest.files['shrunk_int8.bin'].chunks.length, 7);
});

test('first visit fetches every chunk; the second visit fetches nothing but the manifest', { skip }, async () => {
  const caches = fakeCaches(), a = server(), progress = [];
  const parts = await loadBundle({ base: 'https://x/bot/', fetchImpl: a.fetchImpl, cacheStorage: caches, onProgress: (d, t) => progress.push([d, t]) });
  const chunkCount = Object.values(manifest.files).reduce((n, f) => n + f.chunks.length, 0);
  assert.equal(a.log.length, 1 + chunkCount);
  assert.deepEqual(progress.at(-1), [manifest.totalBytes, manifest.totalBytes]);
  const b = server();
  await loadBundle({ base: 'https://x/bot/', fetchImpl: b.fetchImpl, cacheStorage: caches });
  assert.deepEqual(b.log, ['bot_files.json']);
  assert.equal(parts.botData.wordings.length, 5038);
});

test('a dropped download resumes at the missing chunk, and a corrupt chunk is refused', { skip }, async () => {
  const caches = fakeCaches();
  const broken = server({ 'shrunk_int8.bin.003': () => new Response('x', { status: 503 }) });
  await assert.rejects(loadBundle({ base: 'https://x/bot/', fetchImpl: broken.fetchImpl, cacheStorage: caches }), /shrunk_int8.bin.003: HTTP 503/);
  const again = server();
  await loadBundle({ base: 'https://x/bot/', fetchImpl: again.fetchImpl, cacheStorage: caches });
  assert.ok(!again.log.includes('shrunk_int8.bin.000') && again.log.includes('shrunk_int8.bin.003'));
  const corrupt = server({ 'vocab.txt.000': () => new Response(new Uint8Array(28277)) });
  await assert.rejects(loadBundle({ base: 'https://x/bot/', fetchImpl: corrupt.fetchImpl, cacheStorage: fakeCaches() }), /does not match its hash/);
});

test('a new bundle version drops the old cache', { skip }, async () => {
  const caches = fakeCaches();
  await caches.open('packsense-bot-oldversion');
  await caches.open('other-site-cache');
  await loadBundle({ base: 'https://x/bot/', fetchImpl: server().fetchImpl, cacheStorage: caches });
  assert.deepEqual([...caches.stores.keys()].sort(), ['other-site-cache', `packsense-bot-${manifest.version}`]);
});

test('the loaded files make a bot that answers like the Python one', { skip: skip || !existsSync(new URL('./data/shrunk/matcher_cases_calibration.json', import.meta.url)) && 'matcher cases are missing' }, async () => {
  const parts = await loadBundle({ base: 'https://x/bot/', fetchImpl: server().fetchImpl, cacheStorage: fakeCaches() });
  const { ask, bot } = createShrunkBot(parts);
  const cases = JSON.parse(readFileSync(new URL('./data/shrunk/matcher_cases_calibration.json', import.meta.url), 'utf8')).filter((c) => !c.prev).slice(0, 12);
  for (const c of cases) {
    const { result } = await ask(c.text);
    assert.equal(result.action, c.action, c.text);
    assert.equal(result.entryId ?? null, c.entry ?? null, c.text);
    assert.equal(bot.reply(result), c.reply);
  }
});

test('data saver and slow connections skip the download', () => {
  assert.equal(shouldLoad(undefined), true);
  assert.equal(shouldLoad({ connection: { effectiveType: '4g', saveData: false } }), true);
  assert.equal(shouldLoad({ connection: { effectiveType: '4g', saveData: true } }), false);
  for (const t of ['slow-2g', '2g', '3g']) assert.equal(shouldLoad({ connection: { effectiveType: t } }), false);
});
