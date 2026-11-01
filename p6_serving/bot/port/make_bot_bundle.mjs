// Cuts the files the browser bot needs into chunks of about 2 MB and writes the manifest the loader reads (bot_files.json).
//
//   node make_bot_bundle.mjs <out_folder>         (from this folder; needs the generated files in data/ and data/shrunk/)
//
// Each chunk is its own file (name.000, name.001 ...) so that a dropped download resumes at the next chunk, and each has a sha256 the loader checks. `version` is the
// hash of all the chunk hashes: it names the browser cache, so a new bundle replaces the old one and an old one is dropped. Prints the size of every file, raw and gzip.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync, brotliCompressSync } from 'node:zlib';

export const CHUNK_BYTES = 2 * 1024 * 1024;
export const FILES = {
  'bot_data.json': 'data/bot_data.json',
  'vocab.txt': 'data/shrunk/vocab.txt',
  'config.json': 'data/shrunk/config.json',
  'manifest_int8.json': 'data/shrunk/manifest_int8.json',
  'learned_pairs.json': 'data/shrunk/learned_pairs.json',
  'wording_scales.f32': 'data/shrunk/wording_scales.f32',
  'wording_vectors_int8.bin': 'data/shrunk/wording_vectors_int8.bin',
  'shrunk_int8.bin': 'data/shrunk/shrunk_int8.bin',
};

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

export function makeBundle(out, base = new URL('./', import.meta.url), report = () => {}) {
  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  const files = {};
  for (const [name, source] of Object.entries(FILES)) {
    const bytes = readFileSync(new URL(source, base));
    const chunks = [];
    for (let start = 0, i = 0; start < bytes.length || i === 0; start += CHUNK_BYTES, i++) {
      const piece = bytes.subarray(start, start + CHUNK_BYTES);
      const path = `${name}.${String(i).padStart(3, '0')}`;
      writeFileSync(join(out, path), piece);
      chunks.push({ path, bytes: piece.length, sha256: sha256(piece) });
    }
    files[name] = { bytes: bytes.length, chunks };
    report(name, bytes.length, gzipSync(bytes, { level: 9 }).length, brotliCompressSync(bytes).length);
  }
  const version = sha256(Buffer.from(Object.values(files).flatMap((f) => f.chunks.map((c) => c.sha256)).join(''))).slice(0, 16);
  const manifest = { version, chunkBytes: CHUNK_BYTES, totalBytes: Object.values(files).reduce((n, f) => n + f.bytes, 0), files };
  writeFileSync(join(out, 'bot_files.json'), JSON.stringify(manifest));
  return manifest;
}

if (process.argv[1]?.endsWith('make_bot_bundle.mjs')) {
  const out = process.argv[2];
  if (!out) throw new Error('usage: node make_bot_bundle.mjs <out_folder>');
  const mb = (n) => (n / 1e6).toFixed(3).padStart(8);
  console.log('file'.padEnd(28), '     raw MB', '    gzip MB', ' brotli MB');
  const manifest = makeBundle(out, undefined, (name, raw, gz, br) => console.log(name.padEnd(28), mb(raw), '  ', mb(gz), '  ', mb(br)));
  console.log(`version ${manifest.version}, ${Object.values(manifest.files).reduce((n, f) => n + f.chunks.length, 0)} chunk files, ${mb(manifest.totalBytes)} MB raw, written to ${out}`);
}
