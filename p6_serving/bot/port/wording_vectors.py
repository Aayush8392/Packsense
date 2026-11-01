"""Makes the catalogue wording vectors for the SHRUNK 8-bit MiniLM (the ones the browser compares a visitor's question against).

    <scratch venv>/Scripts/python.exe -I p6_serving/bot/port/wording_vectors.py

Reads data/shrunk/ (written by export_shrunk_minilm.py) and the current catalogue; writes, next to them:
  wording_vectors_int8.bin   one row of 384 signed bytes per wording, in the order of Matcher.wordings (the order of bot_data.json "wordings")
  wording_scales.f32         one float32 scale per row (max |value| / 127), so value = byte * scale
  wording_vectors.json       count, dimension and the sha256 of the wording list, which the browser checks against bot_data.json before it uses the rows
A wording is embedded exactly as the Python matcher does: the {placeholders} are cut out first (trial_embeddings.plain), then the pruned tokenizer and the 8-bit
network. The forward pass below is the one in export_shrunk_minilm.py (copied: importing that file would redo the whole export).
"""
from __future__ import annotations

import hashlib
import json
import sys
from math import sqrt
from pathlib import Path

import numpy as np
import scipy.special as sp
from tokenizers import Tokenizer

HERE = Path(__file__).resolve().parent
BOT = HERE.parent
sys.path.insert(0, str(BOT))
import catalogue as cat  # noqa: E402
import matcher as mt  # noqa: E402
from trial_embeddings import plain  # noqa: E402

OUT = HERE / "data" / "shrunk"
MAX_POS = 128

tokens = (OUT / "vocab.txt").read_text(encoding="utf-8").split("\n")[:-1]
spec = json.loads(Tokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2").to_str())
spec["model"]["vocab"] = {t: n for n, t in enumerate(tokens)}
spec["added_tokens"], spec["post_processor"], spec["padding"], spec["truncation"] = [], None, None, None
pruned_tok = Tokenizer.from_str(json.dumps(spec))
CLS, SEP = tokens.index("[CLS]"), tokens.index("[SEP]")


def pruned_ids(text: str) -> list[int]:
    return [CLS] + pruned_tok.encode(text, add_special_tokens=False).ids[:MAX_POS - 2] + [SEP]


man = json.loads((OUT / "manifest_int8.json").read_text())
blob = np.frombuffer((OUT / "shrunk_int8.bin").read_bytes(), dtype=np.uint8)


def get(name, fmt, dtype):
    m = man[name][fmt]
    return blob[m["offset"]:m["offset"] + m["length"]].view(dtype).reshape(m["shape"])


W = {}
for name, m in man.items():
    if m["kind"] == "f16":
        W[name] = get(name, "f16", np.float16).astype(np.float32)
    else:
        W[name] = get(name, "q", np.int8).astype(np.float32) * get(name, "scale", np.float16).astype(np.float32)[:, None]


def layer_norm(x, w, b, eps=1e-12):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


def embed(ids: list[int]) -> np.ndarray:
    L = len(ids)
    x = layer_norm(W["word"][ids] + W["pos"][:L] + W["type0"][0], W["emb_ln.w"], W["emb_ln.b"])
    for i in range(6):
        p = f"encoder.layer.{i}."
        q, k, v = (x @ W[p + f"attention.self.{n}.w"].T + W[p + f"attention.self.{n}.b"] for n in ("query", "key", "value"))
        qh, kh, vh = (a.reshape(L, 12, 32).transpose(1, 0, 2) for a in (q, k, v))
        sc = qh @ kh.transpose(0, 2, 1) / np.sqrt(32.0)
        sc = sc - sc.max(-1, keepdims=True)
        pr = np.exp(sc)
        pr /= pr.sum(-1, keepdims=True)
        ctx = (pr @ vh).transpose(1, 0, 2).reshape(L, 384)
        x = layer_norm(x + ctx @ W[p + "attention.output.dense.w"].T + W[p + "attention.output.dense.b"], W[p + "attention.output.LayerNorm.w"], W[p + "attention.output.LayerNorm.b"])
        h = x @ W[p + "intermediate.dense.w"].T + W[p + "intermediate.dense.b"]
        h = 0.5 * h * (1.0 + sp.erf(h / sqrt(2.0)))
        x = layer_norm(x + h @ W[p + "output.dense.w"].T + W[p + "output.dense.b"], W[p + "output.LayerNorm.w"], W[p + "output.LayerNorm.b"])
    e = x.mean(0)
    return e / np.linalg.norm(e)


def wordings_sha(wordings: list[tuple[str, str]]) -> str:
    return hashlib.sha256(json.dumps([[a, b] for a, b in wordings], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> None:
    m = mt.Matcher(cat.load_entries(), cat.load_fixed())
    texts = [plain(w) for _, w in m.wordings]
    cache: dict[str, np.ndarray] = {}
    for t in dict.fromkeys(texts):
        cache[t] = embed(pruned_ids(t))
    vecs = np.stack([cache[t] for t in texts]).astype(np.float32)
    scale = (np.abs(vecs).max(axis=1) / 127.0).astype(np.float32)
    q = np.clip(np.round(vecs / scale[:, None]), -127, 127).astype(np.int8)
    back = q.astype(np.float32) * scale[:, None]
    cos = (back * vecs).sum(1) / np.linalg.norm(back, axis=1)
    (OUT / "wording_vectors_int8.bin").write_bytes(q.tobytes())
    (OUT / "wording_scales.f32").write_bytes(scale.astype("<f4").tobytes())
    (OUT / "wording_vectors.json").write_text(json.dumps({"count": len(texts), "dim": 384, "sha256": wordings_sha(m.wordings)}), encoding="utf-8")
    print(f"{len(texts)} wordings ({len(cache)} distinct texts), rows {q.shape}, bytes {q.nbytes + scale.nbytes}; 8-bit vs float cosine: min {cos.min():.6f}, mean {cos.mean():.6f}")


if __name__ == "__main__":
    main()
