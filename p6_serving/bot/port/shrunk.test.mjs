// Parity of the JavaScript tokenizer and encoder against Python:  node --test shrunk.test.mjs   (from this folder)
// Needs the generated files in data/shrunk/ (export_shrunk_minilm.py writes the model and reference.json; token_cases.json holds the ids of the pruned Python
// tokenizer for the real question sets and some awkward strings). Without them the tests are skipped, not passed.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { makeEncoder } from './shrunk_encoder.mjs';
import { makeTokenizer } from './shrunk_tokenizer.mjs';

const DIR = new URL('./data/shrunk/', import.meta.url);
const file = (name) => new URL(name, DIR);
const ready = ['vocab.txt', 'config.json', 'manifest_int8.json', 'shrunk_int8.bin', 'reference.json'].every((n) => existsSync(file(n)));
const skip = ready ? false : 'generated files are missing in data/shrunk/';

const tokenize = ready && makeTokenizer(readFileSync(file('vocab.txt'), 'utf8'));
const reference = ready && JSON.parse(readFileSync(file('reference.json'), 'utf8'));

test('tokenizer gives the reference ids for the seven samples', { skip }, () => {
  reference.samples.forEach((text, i) => assert.deepEqual(tokenize(text), reference.ids[i], text));
});

test('tokenizer gives the pruned Python tokenizer ids for every real question and awkward string', { skip: skip || !existsSync(file('token_cases.json')) && 'token_cases.json is missing' }, () => {
  const cases = JSON.parse(readFileSync(file('token_cases.json'), 'utf8'));
  const wrong = cases.filter((c) => JSON.stringify(tokenize(c.text)) !== JSON.stringify(c.ids));
  assert.equal(wrong.length, 0, `${wrong.length} of ${cases.length} differ, first: ${JSON.stringify(wrong[0])} -> ${JSON.stringify(wrong[0] && tokenize(wrong[0].text))}`);
});

function loadEncoder() {
  const buffer = readFileSync(file('shrunk_int8.bin'));
  return makeEncoder(JSON.parse(readFileSync(file('config.json'), 'utf8')), JSON.parse(readFileSync(file('manifest_int8.json'), 'utf8')),
    buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));
}

test('encoder gives the NumPy reference embeddings for 300 real questions (the longest included)', { skip: skip || !existsSync(file('embed_cases.json')) && 'embed_cases.json is missing' }, () => {
  const embed = loadEncoder();
  const cases = JSON.parse(readFileSync(file('embed_cases.json'), 'utf8'));
  let lowestCosine = 1, largest = 0;
  for (const { text, ids, emb } of cases) {
    const got = embed(ids);
    let dot = 0;
    got.forEach((v, c) => { dot += v * emb[c]; largest = Math.max(largest, Math.abs(v - emb[c])); });
    lowestCosine = Math.min(lowestCosine, dot);
    assert.ok(dot > 0.99999, `${text}: cosine ${dot}`);
  }
  assert.ok(largest < 1e-4, `largest difference ${largest}`);
  console.log(`  ${cases.length} questions: lowest cosine ${lowestCosine.toFixed(7)}, largest value difference ${largest.toExponential(2)}`);
});

test('encoder gives the reference 8-bit embeddings for the seven samples', { skip }, () => {
  const embed = loadEncoder();
  reference.samples.forEach((text, i) => {
    const got = embed(tokenize(text)), want = reference.int8[i];
    let dot = 0, worst = 0;
    got.forEach((v, c) => { dot += v * want[c]; worst = Math.max(worst, Math.abs(v - want[c])); });
    assert.ok(dot > 0.99999, `${text}: cosine ${dot}`);
    assert.ok(worst < 1e-4, `${text}: largest difference ${worst}`);
  });
});

const vectorsReady = ready && ['wording_vectors_int8.bin', 'wording_scales.f32', 'wording_vectors.json'].every((n) => existsSync(file(n))) && existsSync(new URL('./data/bot_data.json', import.meta.url));

test('wording vectors belong to the wordings of bot_data.json and agree with the JavaScript encoder', { skip: skip || !vectorsReady && 'wording vector files or bot_data.json are missing' }, async () => {
  const { createHash } = await import('node:crypto');
  const wordings = JSON.parse(readFileSync(new URL('./data/bot_data.json', import.meta.url), 'utf8')).wordings;
  const meta = JSON.parse(readFileSync(file('wording_vectors.json'), 'utf8'));
  assert.equal(wordings.length, meta.count);
  assert.equal(createHash('sha256').update(JSON.stringify(wordings)).digest('hex'), meta.sha256);
  const bytes = readFileSync(file('wording_vectors_int8.bin')), scales = readFileSync(file('wording_scales.f32'));
  assert.equal(bytes.length, meta.count * meta.dim);
  assert.equal(scales.length, meta.count * 4);
  const rows = new Int8Array(bytes.buffer, bytes.byteOffset, bytes.length), scale = new Float32Array(scales.buffer.slice(scales.byteOffset, scales.byteOffset + scales.length));
  const embed = loadEncoder();
  let lowest = 1;
  for (let i = 0; i < meta.count; i += 200) {                     // 26 wordings spread over the catalogue
    const got = embed(tokenize(wordings[i][1].replace(/\{[^}]*\}/g, ' ').trim()));
    let dot = 0, norm = 0;
    for (let c = 0; c < meta.dim; c++) { const v = rows[i * meta.dim + c] * scale[i]; dot += got[c] * v; norm += v * v; }
    lowest = Math.min(lowest, dot / Math.sqrt(norm));
  }
  assert.ok(lowest > 0.9995, `lowest cosine ${lowest}`);
});
