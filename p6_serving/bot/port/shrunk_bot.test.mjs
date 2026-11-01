// The whole bot in JavaScript against the Python pipeline, answer by answer:  node --test shrunk_bot.test.mjs   (from this folder)
// matcher_cases_<set>.json is written by the Python side (make_matcher_cases.py: exact 8-bit model, blend 0.70, confidence 0.60, margin 0.10, learned pairs, pill floor 0.50).
// Without the generated files the tests are skipped, not passed.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { createShrunkBot } from './shrunk_bot.mjs';

const data = (name) => new URL(`./data/${name}`, import.meta.url);
const shrunk = (name) => new URL(`./data/shrunk/${name}`, import.meta.url);
const need = ['bot_data.json', 'shrunk/vocab.txt', 'shrunk/config.json', 'shrunk/manifest_int8.json', 'shrunk/shrunk_int8.bin', 'shrunk/wording_vectors_int8.bin', 'shrunk/wording_scales.f32', 'shrunk/learned_pairs.json'];
const ready = need.every((n) => existsSync(data(n)));

function load() {
  const model = readFileSync(shrunk('shrunk_int8.bin')), bytes = readFileSync(shrunk('wording_vectors_int8.bin')), scales = readFileSync(shrunk('wording_scales.f32'));
  return createShrunkBot({
    botData: JSON.parse(readFileSync(data('bot_data.json'), 'utf8')),
    config: JSON.parse(readFileSync(shrunk('config.json'), 'utf8')),
    manifest: JSON.parse(readFileSync(shrunk('manifest_int8.json'), 'utf8')),
    model: model.buffer.slice(model.byteOffset, model.byteOffset + model.byteLength),
    vocabText: readFileSync(shrunk('vocab.txt'), 'utf8'),
    wordingBytes: new Int8Array(bytes.buffer, bytes.byteOffset, bytes.length),
    wordingScales: new Float32Array(scales.buffer.slice(scales.byteOffset, scales.byteOffset + scales.length)),
    learnedPairs: JSON.parse(readFileSync(shrunk('learned_pairs.json'), 'utf8')),
  });
}

// Only the calibration half: the sealed half has been opened twice and any further look at it is a disclosed decision of the owner, not a test step.
for (const which of ['calibration']) {
  const cases = shrunk(`matcher_cases_${which}.json`);
  test(`JavaScript bot gives the Python answer for every ${which} question`, { skip: !ready ? 'generated files are missing' : !existsSync(cases) && `matcher_cases_${which}.json is missing` }, async () => {
    const { ask, bot } = load();
    const list = JSON.parse(readFileSync(cases, 'utf8'));
    const wrong = [];
    let worst = 0;
    const withoutText = ({ text, ...rest }) => rest;                 // a reply's text is compared on its own, against the Python reply
    for (const c of list) {
      const { result, shown, remember } = await ask(c.text, c.prev);
      const same = result.action === c.action && (result.entryId ?? null) === (c.entry ?? null) && JSON.stringify(result.options) === JSON.stringify(c.options)
        && JSON.stringify(withoutText(shown)) === JSON.stringify(c.shown) && (remember ?? null) === (c.remember ?? null) && bot.reply(result) === c.reply;
      for (let i = 0; i < Math.min(result.ranked.length, c.ranked.length); i++) worst = Math.max(worst, Math.abs(result.ranked[i][1] - c.ranked[i][1]));
      if (!same) wrong.push({ text: c.text, js: { action: result.action, entry: result.entryId, options: result.options, shown }, py: { action: c.action, entry: c.entry, options: c.options, shown: c.shown } });
    }
    console.log(`  ${which}: ${list.length} questions, ${wrong.length} differ, largest score difference ${worst.toExponential(2)}`);
    assert.equal(wrong.length, 0, `${wrong.length} of ${list.length} differ; first: ${JSON.stringify(wrong[0], null, 1)}`);
    assert.ok(worst < 1e-3, `largest score difference ${worst}`);
  });
}

test('entry() names the question and gives the answer of an entry; suggestions are at most four, all with different answers', { skip: !ready ? 'generated files are missing' : false }, async () => {
  const { ask, entry, bot } = load();
  const e = entry('5.1');
  assert.ok(e.question.length > 5 && e.answer.length > 20, JSON.stringify(e));
  const { shown, remember } = await ask('stuff about numbers somewhere');
  assert.equal(shown.kind, 'suggestions');
  assert.ok(shown.entries.length >= 2 && shown.entries.length <= 4);
  assert.equal(new Set(shown.entries.map((id) => bot.answers[bot.canon(id)])).size, shown.entries.length);
  assert.equal(remember, shown.entries[0]);
});
