// Loads the bot's files in the browser without ever blocking the page: chunk by chunk, each chunk checked against its sha256 and kept in the Cache API, so a dropped
// download continues at the next chunk and the next visit needs no download at all. Nothing here runs unless the page calls it (see shouldLoad / whenIdle).
//
//   if (shouldLoad(navigator)) await whenIdle(window); const parts = await loadBundle({ base: '/data/bot/' }); const bot = createShrunkBot(parts);
//
// `cacheStorage` is `caches` in a browser; the tests pass a small stand-in with the same three methods (open, keys, delete).

const CACHE_PREFIX = 'packsense-bot-';
const SLOW = new Set(['slow-2g', '2g', '3g']);

/** False when the visitor asked for less data (Data Saver) or the connection is slow: the keyword matcher then stays the only bot. */
export function shouldLoad(nav) {
  const c = nav && (nav.connection || nav.mozConnection || nav.webkitConnection);
  if (!c) return true;
  return !(c.saveData === true || SLOW.has(c.effectiveType));
}

/** Resolves when the browser is idle (or after a short delay where that is not available), so the first paint and the first interaction come first. */
export function whenIdle(win, timeoutMs = 4000) {
  return new Promise((resolve) => {
    if (win && typeof win.requestIdleCallback === 'function') win.requestIdleCallback(() => resolve(), { timeout: timeoutMs });
    else setTimeout(resolve, 1500);
  });
}

async function sha256Hex(bytes) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Fetches (or takes from the cache) every chunk of every file and joins them. Returns the `parts` that createShrunkBot expects.
 * onProgress(done, total) is called after each chunk with byte counts. Rejects when a chunk cannot be fetched or does not match its hash; chunks already kept stay kept.
 */
export async function loadBundle({ base, fetchImpl = (...a) => globalThis.fetch(...a), cacheStorage = globalThis.caches, onProgress = () => {} }) {
  const manifestResponse = await fetchImpl(`${base}bot_files.json`, { cache: 'no-cache' });
  if (!manifestResponse.ok) throw new Error(`bot_files.json: HTTP ${manifestResponse.status}`);
  const manifest = await manifestResponse.json();
  const name = CACHE_PREFIX + manifest.version;
  const cache = cacheStorage ? await cacheStorage.open(name) : null;
  if (cacheStorage) for (const key of await cacheStorage.keys()) if (key.startsWith(CACHE_PREFIX) && key !== name) await cacheStorage.delete(key);

  let done = 0;
  const bytesOf = async (chunk) => {
    const url = `${base}${chunk.path}`;
    const kept = cache && (await cache.match(url));
    if (kept) {
      const bytes = new Uint8Array(await kept.arrayBuffer());
      if (bytes.length === chunk.bytes && (await sha256Hex(bytes)) === chunk.sha256) return bytes;
    }
    const response = await fetchImpl(url);
    if (!response.ok) throw new Error(`${chunk.path}: HTTP ${response.status}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length !== chunk.bytes || (await sha256Hex(bytes)) !== chunk.sha256) throw new Error(`${chunk.path}: the file does not match its hash`);
    if (cache) await cache.put(url, new Response(bytes));
    return bytes;
  };

  const loaded = {};
  for (const [file, info] of Object.entries(manifest.files)) {
    const joined = new Uint8Array(info.bytes);
    let at = 0;
    for (const chunk of info.chunks) {
      const bytes = await bytesOf(chunk);
      joined.set(bytes, at);
      at += bytes.length;
      done += bytes.length;
      onProgress(done, manifest.totalBytes);
    }
    loaded[file] = joined;
  }

  const text = (file) => new TextDecoder().decode(loaded[file]);
  const model = loaded['shrunk_int8.bin'];
  const scales = loaded['wording_scales.f32'];
  return {
    version: manifest.version,
    botData: JSON.parse(text('bot_data.json')),
    config: JSON.parse(text('config.json')),
    manifest: JSON.parse(text('manifest_int8.json')),
    model: model.buffer.slice(model.byteOffset, model.byteOffset + model.byteLength),
    vocabText: text('vocab.txt'),
    wordingBytes: new Int8Array(loaded['wording_vectors_int8.bin'].buffer),
    wordingScales: new Float32Array(scales.buffer.slice(scales.byteOffset, scales.byteOffset + scales.byteLength)),
    learnedPairs: JSON.parse(text('learned_pairs.json')),
  };
}
