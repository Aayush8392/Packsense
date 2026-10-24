// Parity check between the Python matcher and matcher.js on the fixed list of existing questions (make_parity_list.py). NOT an accuracy test.
//
//   node parity.mjs A   stage A: query embeddings are Python's own, so any difference comes from the port itself
//   node parity.mjs B   stage B: query embeddings come from the quantised model through Transformers.js (embed.js); differences are listed and explained
import { readFileSync } from "node:fs";
import { Bot } from "./matcher.js";

const stage = (process.argv[2] || "A").toUpperCase();
const dir = new URL("./data/", import.meta.url);
const data = JSON.parse(readFileSync(new URL("bot_data.json", dir), "utf8"));
const buf = readFileSync(new URL("wording_embeddings.f32", dir));
const emb = new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
const cases = JSON.parse(readFileSync(new URL("parity_cases.json", dir), "utf8"));

let embedFn;
if (stage === "A") {
  const table = JSON.parse(readFileSync(new URL("parity_query_embeddings.json", dir), "utf8"));
  embedFn = async (p) => {
    if (!table[p]) throw new Error("no Python embedding for: " + p);
    return Float32Array.from(table[p]);
  };
} else {
  const { makeEmbedder } = await import("./embed.js");
  embedFn = await makeEmbedder();
}

const bot = new Bot(data, emb, embedFn);
const diffs = [];
let maxScore = 0;
const t0 = Date.now();
for (const c of cases) {
  const r = await bot.match(c.text, c.prev);
  const same = r.action === c.py.action && (r.entryId ?? null) === (c.py.entry ?? null) && JSON.stringify(r.options) === JSON.stringify(c.py.options) && JSON.stringify(r.ranked.map((x) => x[0])) === JSON.stringify(c.py.ranked.map((x) => x[0]));
  if (r.ranked.length && c.py.ranked.length) maxScore = Math.max(maxScore, Math.abs(r.ranked[0][1] - c.py.ranked[0][1]));
  if (!same) diffs.push({ text: c.text, prev: c.prev, py: c.py, js: { action: r.action, entry: r.entryId, options: r.options, ranked: r.ranked } });
}
console.log(`stage ${stage}: ${cases.length} cases in ${((Date.now() - t0) / 1000).toFixed(1)} s; differences: ${diffs.length}; largest top-score difference: ${maxScore.toExponential(2)}`);
const sameReply = cases.length - diffs.filter((d) => d.py.action !== d.js.action || (d.py.entry ?? null) !== (d.js.entry ?? null) || JSON.stringify(d.py.options) !== JSON.stringify(d.js.options)).length;
console.log(`same visible reply (action, entry, options): ${sameReply} of ${cases.length}`);
const moves = {};
for (const d of diffs) {
  if (d.py.action !== d.js.action || (d.py.entry ?? null) !== (d.js.entry ?? null) || JSON.stringify(d.py.options) !== JSON.stringify(d.js.options)) {
    const k = d.py.action === d.js.action ? d.py.action + " (other entry or options)" : d.py.action + " -> " + d.js.action;
    moves[k] = (moves[k] || 0) + 1;
  }
}
console.log("visible changes by kind:", JSON.stringify(moves));
const VISIBLE_ONLY = process.env.VISIBLE_ONLY === "1";
for (const d of diffs.filter((d) => !VISIBLE_ONLY || d.py.action !== d.js.action || (d.py.entry ?? null) !== (d.js.entry ?? null) || JSON.stringify(d.py.options) !== JSON.stringify(d.js.options)).slice(0, 80)) {
  console.log("---", JSON.stringify(d.text), d.prev ? "prev " + d.prev : "");
  console.log("  py", d.py.action, d.py.entry, JSON.stringify(d.py.options), JSON.stringify(d.py.ranked.map((x) => [x[0], +x[1].toFixed(4)])));
  console.log("  js", d.js.action, d.js.entry, JSON.stringify(d.js.options), JSON.stringify(d.js.ranked.map((x) => [x[0], +x[1].toFixed(4)])));
}
