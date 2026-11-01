// The question bot with the shrunk 8-bit MiniLM: matcher.js (the port of the Python matcher) + shrunk_tokenizer/encoder for the question vectors + the design of
// session 33: learned pairs are not a tie, close answers are combined (up to 120 words), topic pills for questions in the list zone, the refusals as before.
// Settings are the chosen ones for 8 bits (confidence 0.60, margin 0.10, pill floor 0.50). Everything arrives as already-loaded buffers, so the same code runs
// in Node (the tests) and in the browser (the loader of step A.5).
import { Bot } from './matcher.js';
import { makeEncoder } from './shrunk_encoder.mjs';
import { makeTokenizer } from './shrunk_tokenizer.mjs';

// confident: the score the best match needs to be answered straight away (0.70, the owner's choice of 2026-11-02: on the calibration half it halves the wrong direct answers
// compared with 0.60, 9.6% to 5.7% of questions, and the right answer within one click rises from 78.7% to 80.6%; below it the bot offers the nearest questions).
// pills: how many suggested questions a reply that is not an answer offers; closeFrom: from this top score the pills are introduced as close to the question.
// segment: how a long message is matched. 'allmax' = the best score per entry over the whole message and its question pieces (2026-11-02: the whole message carries signal that the
// pieces alone lose, and no length of message does better with the pieces only; 'qmax', the earlier setting, scored worse on long messages).
export const SETTING = { confident: 0.70, margin: 0.10, pills: 4, closeFrom: 0.40, segment: 'allmax', wordCap: 120, learnedMinCount: 2 };

/** Python's np.round: halves go to the even neighbour. */
function roundHalfEven(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

/** The vector stored as 8-bit numbers with one scale, then normalised (vec8 of shrunk_exact_eval.py): applied to the question as well as to the wordings. */
export function vec8(e) {
  let s = 0;
  for (let i = 0; i < e.length; i++) s = Math.max(s, Math.abs(e[i]));
  s = s || 1;
  const out = new Float32Array(e.length);
  let n = 0;
  for (let i = 0; i < e.length; i++) {
    const q = (roundHalfEven((e[i] / s) * 127) / 127) * s;
    out[i] = q;
    n += q * q;
  }
  n = Math.sqrt(n);
  for (let i = 0; i < e.length; i++) out[i] /= n;
  return out;
}

/** The wording matrix the matcher compares against: each stored 8-bit row times its scale, normalised. */
export function wordingMatrix(bytes, scales, dim) {
  const rows = scales.length;
  const out = new Float32Array(rows * dim);
  for (let r = 0; r < rows; r++) {
    let n = 0;
    for (let c = 0; c < dim; c++) {
      const v = bytes[r * dim + c] * scales[r];
      out[r * dim + c] = v;
      n += v * v;
    }
    n = Math.sqrt(n);
    for (let c = 0; c < dim; c++) out[r * dim + c] /= n;
  }
  return out;
}

/**
 * parts: { botData (bot_data.json), config, manifest, model (ArrayBuffer of shrunk_int8.bin), vocabText, wordingBytes (Int8Array), wordingScales (Float32Array),
 *          learnedPairs ([[a, b, count], ...]) }
 */
export function createShrunkBot(parts, setting = SETTING) {
  const { botData, config, manifest, model, vocabText, wordingBytes, wordingScales, learnedPairs } = parts;
  const tokenize = makeTokenizer(vocabText);
  const encode = makeEncoder(config, manifest, model);
  const embedFn = async (text) => vec8(encode(tokenize(text)));
  const constants = { ...botData.constants, CONFIDENT: setting.confident, MARGIN: setting.margin, STRONG: setting.confident + 0.15, LAMBDA: 0.4, BETA: 0.1, VARIANT: setting.segment };
  const bot = new Bot({ ...botData, constants }, wordingMatrix(wordingBytes, wordingScales, config.hidden), embedFn);

  const together = new Map(learnedPairs.filter(([, , n]) => n >= setting.learnedMinCount).map(([a, b]) => [`${a}|${b}`, true]));
  bot.tiedByDesign = (x, y) => {
    const [a, b] = [bot.canon(x), bot.canon(y)].sort();
    if (!together.has(`${a}|${b}`)) return false;
    const fx = bot.familyOf.get(x);
    return !(fx !== undefined && fx === bot.familyOf.get(y));
  };

  const hubs = new Set(bot.families.map((f) => f.hub));
  const words = (id) => bot.answers[bot.canon(id)].split(/\s+/).filter(Boolean).length;

  /**
   * What to show for a result. kind 'answer': `entries` are shown in order (one entry, a hub, or two combined). kind 'suggestions': the bot has no answer it is sure of, so it
   * offers the nearest questions (`entries`, at most `setting.pills`, each with a different answer) and the visitor picks the one meant; `close` says whether the nearest one is
   * close to what was asked. kind 'reply': the fixed text for a refusal. `ranking` is the full ranking of the question (with the memory of the last answer applied).
   */
  function present(res, ranking) {
    const action = res.action === 'answer' && hubs.has(res.entryId) ? 'hub' : res.action;
    if (action === 'hub') return { kind: 'answer', entries: [res.entryId], combined: false, hub: true };
    if (action === 'answer') return { kind: 'answer', entries: [res.entryId], combined: false, hub: false };
    if (action === 'choice' && res.options.length >= 2) {
      const [a, b] = res.options;
      const both = words(a) + words(b) <= setting.wordCap;
      return { kind: 'answer', entries: both ? [a, b] : [a], combined: both, hub: false };
    }
    if (action === 'generic' && ranking.length) {
      const seen = new Set();
      const entries = [];
      for (const [id] of ranking) {
        const canon = bot.canon(id);
        if (seen.has(bot.answers[canon])) continue;
        seen.add(bot.answers[canon]);
        entries.push(canon);
        if (entries.length === setting.pills) break;
      }
      return { kind: 'suggestions', entries, close: ranking[0][1] >= setting.closeFrom };
    }
    return { kind: 'reply', action, text: bot.reply(res) };
  }

  /**
   * Answer a question. `prevId` is the entry the conversation last settled on (so a short follow-up can lean on it), or null. `remember` is what to pass as `prevId` next
   * time: the entry shown, or the nearest one when the bot only offered suggestions.
   */
  async function ask(text, prevId = null) {
    const result = await bot.match(text, prevId);
    const shown = present(result, bot.rankedWithContext(text, prevId));
    const remember = shown.kind === 'answer' ? shown.entries[0] : (result.entryId ?? result.ranked[0]?.[0] ?? null);
    return { result, shown, remember };
  }

  const questionOf = new Map();
  for (const [id, wording] of bot.wordings) if (!questionOf.has(id)) questionOf.set(id, wording);

  /** The question an entry answers (its first wording) and its answer text. */
  function entry(id) {
    const canon = bot.canon(id);
    return { question: questionOf.get(canon) ?? questionOf.get(id) ?? '', answer: bot.answers[canon] };
  }

  return { bot, ask, present, entry, embed: embedFn };
}
