// The question matcher for the browser: a line-by-line port of the frozen Python matcher (p6_serving/bot/matcher.py, segment.py, segment_matcher.py and the
// HybridMatcher of trial_embeddings.py). It uses no model to write answers: it ranks prepared catalogue answers with word and 3-letter scores plus a small
// sentence-embedding model (all-MiniLM-L6-v2), and shows the closest options when it is unsure.
//
// Everything it needs (wordings, answers, families, synonyms, constants, the regular expressions as source text) is read from bot_data.json, which
// export_bot_data.py writes from the Python modules, so the two versions cannot drift apart. The embeddings of the catalogue wordings come in a float32 file.
//
// Dictionaries whose iteration order matters for the sums (term vectors) are Maps, as Python dicts keep insertion order and plain objects would reorder digit keys.

const UWORD = "\\p{L}\\p{N}_";
const BOUNDARY = `(?:(?<![${UWORD}])(?=[${UWORD}])|(?<=[${UWORD}])(?![${UWORD}]))`;

// Python's \b, \w and \d are Unicode-aware; JavaScript's are ASCII-only. Rewrite the three so the same pattern text means the same thing.
export function pyRegex(source, pyFlags) {
  let out = "";
  let inClass = false;
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (c === "\\") {
      const n = source[i + 1];
      i++;
      if (n === "b" && !inClass) out += BOUNDARY;
      else if (n === "w") out += inClass ? UWORD : `[${UWORD}]`;
      else if (n === "d") out += "\\p{Nd}";
      else out += c + n;
      continue;
    }
    if (c === "[" && !inClass) inClass = true;
    else if (c === "]" && inClass) inClass = false;
    out += c;
  }
  return new RegExp(out, "u" + (pyFlags & 2 ? "i" : ""));
}

export function plain(text) {
  return text.replace(/\{[^}]*\}/g, " ").trim();
}

function pyStrip(s, chars) {
  let a = 0;
  let b = s.length;
  while (a < b && chars.includes(s[a])) a++;
  while (b > a && chars.includes(s[b - 1])) b--;
  return s.slice(a, b);
}

function countWords(s) {
  return s.trim().split(/\s+/).filter(Boolean).length;
}

// difflib.SequenceMatcher(None, a, b).ratio() without junk, for short words (the close-match test for typos).
function ratio(a, b) {
  const total = a.length + b.length;
  if (total === 0) return 1.0;
  const b2j = new Map();
  for (let j = 0; j < b.length; j++) {
    if (!b2j.has(b[j])) b2j.set(b[j], []);
    b2j.get(b[j]).push(j);
  }
  const longest = (alo, ahi, blo, bhi) => {
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map();
      for (const j of b2j.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestsize) {
          besti = i - k + 1;
          bestj = j - k + 1;
          bestsize = k;
        }
      }
      j2len = newj2len;
    }
    return [besti, bestj, bestsize];
  };
  let matches = 0;
  const queue = [[0, a.length, 0, b.length]];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const [i, j, k] = longest(alo, ahi, blo, bhi);
    if (k) {
      matches += k;
      if (alo < i && blo < j) queue.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
    }
  }
  return (2.0 * matches) / total;
}

class Space {
  constructor(docs) {
    const df = new Map();
    for (const d of docs) for (const f of new Set(d)) df.set(f, (df.get(f) || 0) + 1);
    const n = docs.length;
    this.idf = new Map();
    for (const [f, c] of df) this.idf.set(f, Math.log((1 + n) / (1 + c)) + 1);
    this.default = Math.log(1 + n) + 1;
  }

  vec(feats) {
    const tf = new Map();
    for (const f of feats) tf.set(f, (tf.get(f) || 0) + 1);
    const v = new Map();
    let sq = 0;
    for (const [f, c] of tf) {
      const x = (1 + Math.log(c)) * (this.idf.has(f) ? this.idf.get(f) : this.default);
      v.set(f, x);
      sq += x * x;
    }
    const norm = Math.sqrt(sq) || 1.0;
    for (const [f, x] of v) v.set(f, x / norm);
    return v;
  }
}

function dot(a, b) {
  if (a.size > b.size) [a, b] = [b, a];
  let s = 0;
  for (const [f, x] of a) s += x * (b.get(f) || 0);
  return s;
}

function setMinus(a, b) {
  let n = 0;
  for (const x of a) if (!b.has(x)) n++;
  return n;
}

export class Bot {
  // data: parsed bot_data.json; emb: Float32Array of all wording embeddings; embedFn: async (plain text) => Float32Array (normalised)
  constructor(data, emb, embedFn) {
    this.d = data;
    this.k = data.constants;
    this.embedFn = embedFn;
    this.cache = new Map();
    this.stop = new Set(data.stop);
    this.syn = new Map(Object.entries(data.synonyms));
    this.subjectsAll = new Set(data.subjects);
    this.rx = Object.fromEntries(Object.entries(data.regexes).map(([n, [p, f]]) => [n, pyRegex(p, f)]));
    this.entryIds = data.entries.map((e) => e.id);
    this.kind = Object.fromEntries(data.entries.map((e) => [e.id, e.kind]));
    this.alias = data.alias;
    this.answers = data.answers;
    this.wordings = data.wordings;
    this.dim = emb.length / this.wordings.length;
    this.emb = emb;

    this.wordSpace = new Space([...this.wordings.map(([, w]) => this.tokens(w)), ...Object.values(this.answers).map((a) => this.tokens(a))]);
    this.charSpace = new Space(this.wordings.map(([, w]) => this.trigrams(w)));
    this.wordVecs = this.wordings.map(([, w]) => this.wordSpace.vec(this.tokens(w)));
    this.charVecs = this.wordings.map(([, w]) => this.charSpace.vec(this.trigrams(w)));
    this.answerVecs = {};
    for (const [id, a] of Object.entries(this.answers)) this.answerVecs[id] = this.wordSpace.vec(this.tokens(a));
    this.openers = this.wordings.map(([, w]) => this.opener(w));
    this.subjects = this.wordings.map(([, w]) => new Set(this.tokens(w).filter((t) => this.subjectsAll.has(t))));
    this.vocab = [...this.wordSpace.idf.keys()].sort();
    this.takesName = new Set(this.wordings.filter(([, w]) => w.includes("{brand}") || w.includes("{product}")).map(([id]) => id));
    this.families = data.families;
    this.familyOf = new Map();
    this.families.forEach((f, i) => {
      for (const id of [f.hub, ...f.details]) this.familyOf.set(id, i);
    });
    this.lexLast = null;
    this.centroids = null;
  }

  // --- text -----------------------------------------------------------------------------------------------------------------------------------
  stem(w) {
    w = this.syn.has(w) ? this.syn.get(w) : w;
    for (const suf of ["ing", "ed", "es", "s"]) {
      if (w.length > 4 && w.endsWith(suf)) {
        w = w.slice(0, w.length - suf.length);
        break;
      }
    }
    return this.syn.has(w) ? this.syn.get(w) : w;
  }

  tokens(text) {
    text = text.toLowerCase().replace(/\{[^}]*\}/g, " ");
    text = text.split("'s").join("").split("open food facts").join("openfoodfacts");
    const words = (text.match(/[a-z0-9]+/g) || []).map((w) => this.stem(w));
    return words.filter((w) => !this.stop.has(w));
  }

  trigrams(text) {
    const t = " " + this.tokens(text).join(" ") + " ";
    const out = [];
    for (let i = 0; i < t.length - 2; i++) out.push(t.slice(i, i + 3));
    return out;
  }

  opener(text) {
    const t = text.trim().toLowerCase();
    for (const w of this.d.wh) {
      if (t.startsWith(w + " ") || t === w) return w === "do" || w === "does" ? "does" : w === "is" || w === "are" ? "is" : w;
    }
    return "";
  }

  looksNotEnglish(q) {
    q = q.replace(/’/g, "'");
    const letters = Array.from(q).filter((c) => /\p{L}/u.test(c));
    if (!letters.length) return false;
    if (letters.some((c) => c.codePointAt(0) > 0x24f)) return true;
    const accented = letters.filter((c) => c.codePointAt(0) > 127).length;
    return accented / letters.length > 0.08 || this.rx.ROMAN_HINDI.test(q) || this.rx.OTHER_LANGUAGE_WORDS.test(q) || q.startsWith("¿") || q.startsWith("¡");
  }

  // --- embeddings -----------------------------------------------------------------------------------------------------------------------------
  async prepare(query) {
    const texts = [query];
    if (this.isLong(query)) texts.push(...this.questionPieces(query));
    for (const t of texts) {
      const p = plain(t);
      if (!this.cache.has(p)) this.cache.set(p, await this.embedFn(p));
    }
  }

  // --- segments (long messages) ---------------------------------------------------------------------------------------------------------------
  isLong(message) {
    return countWords(message) >= this.k.LONG_WORDS;
  }

  pieces(message) {
    const parts = message
      .split(this.splitter())
      .filter((p) => p !== undefined && p !== "" && pyStrip(p, " ,.;") !== "")
      .map((p) => pyStrip(p.replace(this.rx.SEG_LEAD, ""), " ,.;"));
    return parts.filter((p) => countWords(p) >= this.k.MIN_PIECE);
  }

  splitter() {
    if (!this._split) this._split = new RegExp(this.rx.SEG_BREAK.source, this.rx.SEG_BREAK.flags + "g");
    return this._split;
  }

  questionPieces(message) {
    return this.pieces(message).filter((p) => this.rx.SEG_QUESTION.test(p));
  }

  // --- scores ---------------------------------------------------------------------------------------------------------------------------------
  unknownWords(query) {
    let n = 0;
    for (const w of this.tokens(query)) {
      if (/^[0-9]+$/.test(w) || this.wordSpace.idf.has(w)) continue;
      let close = false;
      for (const v of this.vocab) {
        if (ratio(v, w) >= 0.8) {
          close = true;
          break;
        }
      }
      if (!close) n++;
    }
    return n;
  }

  lexScores(query) {
    const k = this.k;
    const qw = this.wordSpace.vec(this.tokens(query));
    const qc = this.charSpace.vec(this.trigrams(query));
    const qo = this.opener(query);
    const qs = new Set(this.tokens(query).filter((t) => this.subjectsAll.has(t)));
    const best = new Map();
    for (let i = 0; i < this.wordings.length; i++) {
      const eid = this.wordings[i][0];
      let s = k.WEIGHT_WORD * dot(qw, this.wordVecs[i]) + k.WEIGHT_CHAR * dot(qc, this.charVecs[i]);
      if (qo && this.openers[i]) s += qo === this.openers[i] ? k.WH_BONUS : -k.WH_BONUS / 2;
      s -= k.SUBJECT_MISS * setMinus(qs, this.subjects[i]) + (k.SUBJECT_MISS / 2) * setMinus(this.subjects[i], qs);
      if (s > (best.has(eid) ? best.get(eid) : -1.0)) best.set(eid, s);
    }
    const oov = this.unknownWords(query);
    const out = [];
    for (const id of this.entryIds) {
      const base = best.has(id) ? best.get(id) : 0.0;
      let score = base + k.WEIGHT_ANSWER * dot(qw, this.answerVecs[id]);
      if (oov && !this.takesName.has(id)) score *= Math.pow(k.OOV_FACTOR, Math.min(oov, 2));
      out.push([id, score]);
    }
    return out.sort((a, b) => b[1] - a[1]);
  }

  hybridScores(query) {
    const lexList = this.lexScores(query);
    const lex = new Map(lexList);
    const q = this.cache.get(plain(query));
    if (!q) throw new Error("embedding not prepared for: " + query);
    const best = new Map();
    const dim = this.dim;
    for (let i = 0; i < this.wordings.length; i++) {
      let s = 0;
      const off = i * dim;
      for (let j = 0; j < dim; j++) s += this.emb[off + j] * q[j];
      const eid = this.wordings[i][0];
      if (s > (best.has(eid) ? best.get(eid) : -1.0)) best.set(eid, s);
    }
    this.lexLast = lex;
    const a = this.k.ALPHA;
    const out = [];
    for (const [id, l] of lex) out.push([id, a * (best.has(id) ? best.get(id) : 0.0) + (1 - a) * l]);
    return out.sort((x, y) => y[1] - x[1]);
  }

  scores(query) {
    const whole = this.hybridScores(query);
    if (this.k.VARIANT === "none" || !this.isLong(query)) return whole;
    const qs = this.questionPieces(query);
    if (!qs.length) return whole;
    const best = new Map();
    const lexBest = new Map();
    for (const p of qs) {
      for (const [id, s] of this.hybridScores(p)) if (s > (best.has(id) ? best.get(id) : -9.0)) best.set(id, s);
      for (const [id, v] of this.lexLast) if (v > (lexBest.has(id) ? lexBest.get(id) : -9.0)) lexBest.set(id, v);
    }
    this.lexLast = lexBest;
    return [...best.entries()].sort((a, b) => b[1] - a[1]);
  }

  // --- decisions ------------------------------------------------------------------------------------------------------------------------------
  isClear(topId, top, rival, query) {
    const margin = this.k.MARGIN + (this.tokens(query).length <= 2 ? this.k.SHORT_EXTRA : 0.0);
    if (this.k.DATA_NEEDS_CUE && this.kind[topId] === "data" && !this.rx.COUNT_CUE.test(query)) return false;
    return top - rival >= margin;
  }

  rivalOf(ranked) {
    const topAns = this.answers[ranked[0][0]];
    for (let i = 1; i < ranked.length; i++) if (this.answers[ranked[i][0]] !== topAns) return ranked[i][1];
    return 0.0;
  }

  tieResult(ranked, top, query = "") {
    const topId = ranked[0][0];
    const rivalId = (ranked.slice(1).find(([id]) => this.answers[id] !== this.answers[topId]) || [null])[0];
    const r = this.rx;
    if (rivalId === null || [r.REQUEST_CUE, r.ADVICE, r.HEALTH_MORE, r.MEDICAL, r.TRICK, r.NOT_OFFERED_CUE].some((x) => x.test(query))) {
      return { action: "generic", entryId: null, score: top, ranked: ranked.slice(0, 3), options: [] };
    }
    const lex = this.lexLast;
    if (this.k.LEX_FLOOR > 0 && lex && Math.max(lex.get(topId) || 0.0, lex.get(rivalId) || 0.0) < this.k.LEX_FLOOR) {
      return { action: "generic", entryId: null, score: top, ranked: ranked.slice(0, 3), options: [] };
    }
    const fa = this.familyOf.get(topId);
    const fb = this.familyOf.get(rivalId);
    if (fa !== undefined && fa === fb) {
      const f = this.families[fa];
      return { action: "hub", entryId: f.hub, score: top, ranked: ranked.slice(0, 3), options: [...f.details] };
    }
    const options = [topId, rivalId];
    const third = ranked.slice(1).find(([id, sc]) => !options.includes(id) && ![this.answers[topId], this.answers[rivalId]].includes(this.answers[id]) && sc >= top - this.k.THIRD_WINDOW);
    return { action: "choice", entryId: null, score: top, ranked: ranked.slice(0, 3), options: third ? [...options, third[0]] : options };
  }

  canon(id) {
    return id && this.alias[id] ? this.alias[id] : id;
  }

  matchSync(query) {
    const q = query.trim();
    const r = this.rx;
    const k = this.k;
    const res = (action, entryId, score, ranked) => ({ action, entryId: entryId ?? null, score: score ?? 0, ranked: ranked ?? [], options: [] });
    if (r.BARCODE.test(q) || r.BARCODE_WORD.test(q)) {
      const rest = this.tokens(q.replace(new RegExp(r.BARCODE.source, "gu"), " ")).filter((w) => !/^[0-9]+$/.test(w) && !["look", "lookup", "up", "barcode", "bar", "code", "search", "find", "check"].includes(w));
      return res(rest.length <= 2 ? "barcode" : "productfacts");
    }
    if (this.looksNotEnglish(q)) return res("english_only");
    const ranked = this.scores(q);
    const [topId, top] = ranked[0];
    const rival = this.rivalOf(ranked);
    const clear = this.isClear(topId, top, rival, q);
    const top3 = ranked.slice(0, 3);
    if (top < k.NEAR_EXACT) {
      if (r.TRICK.test(q)) return res(r.ADVICE.test(q) || r.HEALTH_MORE.test(q) ? "advice" : "meta", null, top, top3);
      if (r.PREDICT.test(q)) return res("time", null, top, top3);
      if (r.RANK_CUE.test(q) && !r.COMPLETENESS.test(q)) return res("ranking", null, top, top3);
      if (r.OPINION.test(q)) return res("meta", null, top, top3);
      if (r.PRIVATE_CUE.test(q)) return res("private", null, top, top3);
      if (r.PRODUCT_FACT_CUE.test(q)) return res("productfacts", null, top, top3);
      if (r.OUTSIDE_CUE.test(q) || (r.COMPARE_CUE.test(q) && this.unknownWords(q) >= 1)) return res("meta", null, top, top3);
    }
    if (top >= k.STRONG && clear) return res("answer", topId, top, top3);
    if (r.MEDICAL.test(q)) return res("medical", null, top, top3);
    if ((r.ADVICE.test(q) || r.HEALTH_MORE.test(q)) && top < k.CONFIDENT + 0.1) return res("advice", null, top, top3);
    if (top >= k.CONFIDENT && clear) return res("answer", topId, top, top3);
    if (top >= k.CONFIDENT) return this.tieResult(ranked, top, q);
    return res("generic", null, top, top3);
  }

  // --- follow-ups (memory of the last answer) -------------------------------------------------------------------------------------------------
  isFollowUpCandidate(q) {
    return this.tokens(q).length <= this.k.SHORT || this.rx.PRONOUN.test(q) || this.rx.FOLLOW_OPENER.test(q.trim());
  }

  getCentroids() {
    if (this.centroids) return this.centroids;
    const docs = new Map();
    const add = (id, toks) => {
      if (!docs.has(id)) docs.set(id, []);
      docs.get(id).push(...toks);
    };
    for (const [id, w] of this.wordings) add(id, this.tokens(w));
    for (const [id, a] of Object.entries(this.answers)) add(id, this.tokens(a));
    this.centroids = new Map([...docs].map(([id, toks]) => [id, this.wordSpace.vec(toks)]));
    return this.centroids;
  }

  matchInContextSync(query, prevId) {
    const base = this.matchSync(query);
    prevId = this.canon(prevId);
    if (!prevId || ["barcode", "english_only", "medical"].includes(base.action) || !this.isFollowUpCandidate(query)) return base;
    const cent = this.getCentroids();
    const prev = cent.get(prevId) || new Map();
    const buttons = new Set(this.d.followups[prevId] || []);
    const empty = new Map();
    const ranked = this.scores(query)
      .map(([id, s]) => [id, s + (id === prevId ? 0.0 : this.k.LAMBDA * dot(prev, cent.get(id) || empty)) + (buttons.has(id) ? this.k.BETA : 0.0)])
      .sort((a, b) => b[1] - a[1]);
    const [topId, top] = ranked[0];
    const rival = this.rivalOf(ranked);
    if (top >= this.k.CONFIDENT && this.isClear(topId, top, rival, query)) return { action: "answer", entryId: topId, score: top, ranked: ranked.slice(0, 3), options: [] };
    if (top >= this.k.CONFIDENT) return this.tieResult(ranked, top, query);
    return { action: "generic", entryId: null, score: top, ranked: ranked.slice(0, 3), options: [] };
  }

  // --- public ---------------------------------------------------------------------------------------------------------------------------------
  async match(query, prevId = null) {
    await this.prepare(query);
    return prevId ? this.matchInContextSync(query, prevId) : this.matchSync(query);
  }

  reply(result) {
    if (result.action === "answer" || result.action === "hub") return this.answers[result.entryId];
    if (result.action === "choice") return this.d.replies.choice;
    if (result.action === "generic") return this.d.replies.generic;
    return this.d.replies.groups[result.action];
  }
}
