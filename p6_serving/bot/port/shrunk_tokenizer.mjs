// BERT-uncased tokenizer for the shrunk MiniLM: the algorithm of the Python `tokenizers` BertNormalizer + BertPreTokenizer + WordPiece, run on the pruned
// vocabulary in data/shrunk/vocab.txt (one piece per line, line number = id). Output is the id list the shrunk encoder expects: [CLS] pieces [SEP], cut at 128.

const MAX_POSITIONS = 128;
const MAX_WORD_CHARS = 100;

const CONTROL = /[\p{Cc}\p{Cf}]/u;
const MARKS = /\p{Mn}/gu;
const PUNCTUATION = /[\p{P}!-/:-@[-`{-~]/u;
const CJK = /[㐀-䶿一-鿿豈-﫿\u{20000}-\u{2a6df}\u{2a700}-\u{2b73f}\u{2b740}-\u{2b81f}\u{2b820}-\u{2ceaf}\u{2f800}-\u{2fa1f}]/u;

function clean(text) {
  let out = '';
  for (const ch of text) {
    if (ch === '\t' || ch === '\n' || ch === '\r') out += ' ';
    else if (ch === '\0' || ch === '�' || CONTROL.test(ch)) continue;
    else if (/\p{Zs}/u.test(ch)) out += ' ';
    else if (CJK.test(ch)) out += ` ${ch} `;
    else out += ch;
  }
  return out;
}

function words(text) {
  const normal = clean(text).normalize('NFD').replace(MARKS, '').toLowerCase();
  const out = [];
  for (const chunk of normal.split(/\s+/)) {
    if (!chunk) continue;
    let current = '';
    for (const ch of chunk) {
      if (PUNCTUATION.test(ch)) {
        if (current) out.push(current);
        out.push(ch);
        current = '';
      } else current += ch;
    }
    if (current) out.push(current);
  }
  return out;
}

export function makeTokenizer(vocabText, { unk = '[UNK]', cls = '[CLS]', sep = '[SEP]' } = {}) {
  const pieces = vocabText.split('\n');
  if (pieces[pieces.length - 1] === '') pieces.pop();
  const idOf = new Map(pieces.map((p, i) => [p, i]));
  const UNK = idOf.get(unk), CLS = idOf.get(cls), SEP = idOf.get(sep);

  function wordPiece(word) {
    const chars = Array.from(word);
    if (chars.length > MAX_WORD_CHARS) return [UNK];
    const ids = [];
    let start = 0;
    while (start < chars.length) {
      let end = chars.length, found = null;
      while (start < end) {
        const piece = (start > 0 ? '##' : '') + chars.slice(start, end).join('');
        if (idOf.has(piece)) { found = idOf.get(piece); break; }
        end -= 1;
      }
      if (found === null) return [UNK];
      ids.push(found);
      start = end;
    }
    return ids;
  }

  return function encode(text) {
    const ids = [];
    for (const w of words(text)) ids.push(...wordPiece(w));
    return [CLS, ...ids.slice(0, MAX_POSITIONS - 2), SEP];
  };
}
