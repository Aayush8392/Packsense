"""Exports the SHRUNK MiniLM for the browser (owner's route, 2026-11-01): pruned vocabulary, 8-bit and 4-bit weights, plus a NumPy reference forward pass that the JavaScript port must match.

    python export_shrunk_minilm.py            # writes data/shrunk/*  (generated; not tracked)

What it makes (all-MiniLM-L6-v2, 22.7M parameters -> 12.9M):
  vocab.txt            the kept word pieces in new-id order (one per line); the browser tokenizer is BERT uncased with THIS vocabulary
  config.json          sizes of the network
  shrunk_int8.bin + manifest_int8.json   weights as 8 bits (one scale per row)
  shrunk_int4.bin + manifest_int4.json   weights as 4 bits (blocks of 32 numbers, one scale per block)
  reference.json       test inputs with the expected embeddings, for parity tests of the JavaScript port
The catalogue (wordings, answers, families ...) comes from bot_data.json as before; the wording vectors are made by wording_vectors.py once the shrunk model is chosen.
Kept vocabulary: the tokens used by the catalogue (wordings and answers) and the older question sets, all specials, single characters and one- or two-character word pieces.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import torch  # noqa: F401
from tokenizers import Tokenizer
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
BOT = HERE.parent
sys.path.insert(0, str(BOT))
sys.path.insert(0, str(HERE.parents[2] / "reviews" / "13_set"))
import catalogue as cat  # noqa: E402

OUT = HERE / "data" / "shrunk"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "sentence-transformers/all-MiniLM-L6-v2"
MAX_POS = 128          # queries are capped at 300 characters, far under 128 pieces
BLOCK = 32

st = SentenceTransformer(BASE)
tok = st.tokenizer
bert = st[0].auto_model.eval()
sd = {k: v.detach().cpu().float().numpy() for k, v in bert.state_dict().items()}


def used_tokens() -> set[int]:
    used = set()
    entries, fixed = cat.load_entries(), cat.load_fixed()
    for e in entries:
        for w in cat.wordings(e) + [cat.render(e, fixed)]:
            used.update(tok(re.sub(r"\{[^}]*\}", " ", w), add_special_tokens=False)["input_ids"])
    import reranker as rr
    for src, rows in rr.load_sources(entries).items():
        for r in rows:
            used.update(tok(r["text"], add_special_tokens=False)["input_ids"])
    return used


vocab = tok.get_vocab()
inv = {i: t for t, i in vocab.items()}
keep = used_tokens() | set(tok.all_special_ids)
for t, i in vocab.items():
    core = t[2:] if t.startswith("##") else t
    if len(core) <= (2 if t.startswith("##") else 1):
        keep.add(i)
old_ids = sorted(keep)                       # new id n  <->  old id old_ids[n]
new_of_old = {o: n for n, o in enumerate(old_ids)}
tokens = [inv[o] for o in old_ids]
(OUT / "vocab.txt").write_text("\n".join(tokens) + "\n", encoding="utf-8", newline="\n")
print(f"kept vocabulary: {len(tokens)} of {len(vocab)} pieces")

# the pruned tokenizer, built from the original with only the kept pieces (this is the algorithm the browser reproduces)
spec = json.loads(tok.backend_tokenizer.to_str())
spec["model"]["vocab"] = {t: n for n, t in enumerate(tokens)}
spec["added_tokens"] = []
spec["post_processor"] = None
pruned_tok = Tokenizer.from_str(json.dumps(spec))
UNK, CLS, SEP = tokens.index("[UNK]"), tokens.index("[CLS]"), tokens.index("[SEP]")


def pruned_ids(text: str) -> list[int]:
    return [CLS] + pruned_tok.encode(text, add_special_tokens=False).ids[:MAX_POS - 2] + [SEP]


# ---------------------------------------------------------------- quantisation ---------------------------------------------------------------------------------------
def q8(w: np.ndarray):
    scale = np.maximum(np.abs(w).max(axis=1), 1e-8) / 127.0
    q = np.clip(np.round(w / scale[:, None]), -127, 127).astype(np.int8)
    return q, scale.astype(np.float16)


def q4(w: np.ndarray):
    r, c = w.shape
    wb = w.reshape(r, c // BLOCK, BLOCK)
    scale = np.maximum(np.abs(wb).max(axis=2), 1e-8) / 7.0
    q = np.clip(np.round(wb / scale[:, :, None]), -7, 7).astype(np.int8) + 8       # 1..15
    flat = q.reshape(r, c).astype(np.uint8)
    packed = (flat[:, 0::2] | (flat[:, 1::2] << 4)).astype(np.uint8)               # low nibble = even position
    return packed, scale.astype(np.float16)


def deq8(q, scale):
    return q.astype(np.float32) * scale.astype(np.float32)[:, None]


def deq4(packed, scale, cols):
    lo, hi = (packed & 0x0F).astype(np.int8) - 8, (packed >> 4).astype(np.int8) - 8
    q = np.empty((packed.shape[0], cols), dtype=np.float32)
    q[:, 0::2], q[:, 1::2] = lo, hi
    return (q.reshape(packed.shape[0], cols // BLOCK, BLOCK) * scale.astype(np.float32)[:, :, None]).reshape(packed.shape[0], cols)


LIN = []                                              # (name, is_matrix_to_quantise)
for i in range(6):
    p = f"encoder.layer.{i}."
    for part in ("attention.self.query", "attention.self.key", "attention.self.value", "attention.output.dense", "intermediate.dense", "output.dense"):
        LIN.append(p + part)

tensors = {}                                           # name -> float32 array (full precision source, pruned and cut)
tensors["word"] = sd["embeddings.word_embeddings.weight"][old_ids]
tensors["pos"] = sd["embeddings.position_embeddings.weight"][:MAX_POS]
tensors["type0"] = sd["embeddings.token_type_embeddings.weight"][0:1]
tensors["emb_ln.w"], tensors["emb_ln.b"] = sd["embeddings.LayerNorm.weight"], sd["embeddings.LayerNorm.bias"]
for i in range(6):
    p = f"encoder.layer.{i}."
    for part in ("attention.self.query", "attention.self.key", "attention.self.value", "attention.output.dense", "intermediate.dense", "output.dense"):
        tensors[p + part + ".w"], tensors[p + part + ".b"] = sd[p + part + ".weight"], sd[p + part + ".bias"]
    for part in ("attention.output.LayerNorm", "output.LayerNorm"):
        tensors[p + part + ".w"], tensors[p + part + ".b"] = sd[p + part + ".weight"], sd[p + part + ".bias"]
QUANT = {"word"} | {n + ".w" for n in LIN}


def write(bits: int):
    blob, manifest = bytearray(), {}
    def add(name, arr, fmt):
        off = len(blob)
        blob.extend(arr.tobytes())
        manifest.setdefault(name, {})[fmt] = {"offset": off, "length": arr.nbytes, "shape": list(arr.shape)}
    for name, arr in tensors.items():
        if name in QUANT:
            if bits == 8:
                q, s = q8(arr)
                add(name, q, "q")
                add(name, s, "scale")
            else:
                q, s = q4(arr, ) if False else q4(arr)
                add(name, q, "q")
                add(name, s, "scale")
            manifest[name]["kind"] = f"q{bits}"
            manifest[name]["cols"] = arr.shape[1]
        else:
            add(name, arr.astype(np.float16), "f16")
            manifest[name]["kind"] = "f16"
    (OUT / f"shrunk_int{bits}.bin").write_bytes(bytes(blob))
    (OUT / f"manifest_int{bits}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


(OUT / "config.json").write_text(json.dumps({"hidden": 384, "heads": 12, "layers": 6, "intermediate": 1536, "ln_eps": 1e-12, "max_positions": MAX_POS, "vocab": len(tokens),
                                             "unk": UNK, "cls": CLS, "sep": SEP, "block": BLOCK, "lowercase": True}), encoding="utf-8")
manifests = {8: write(8), 4: write(4)}


# ---------------------------------------------------------------- reference forward pass (the specification for the JavaScript port) ------------------------------------
def load(bits: int) -> dict:
    man = manifests[bits]
    blob = np.frombuffer((OUT / f"shrunk_int{bits}.bin").read_bytes(), dtype=np.uint8)
    def get(name, fmt, dtype):
        m = man[name][fmt]
        return blob[m["offset"]:m["offset"] + m["length"]].view(dtype).reshape(m["shape"])
    out = {}
    for name, m in man.items():
        if m["kind"] == "f16":
            out[name] = get(name, "f16", np.float16).astype(np.float32)
        elif m["kind"] == "q8":
            out[name] = deq8(get(name, "q", np.int8), get(name, "scale", np.float16))
        else:
            out[name] = deq4(get(name, "q", np.uint8), get(name, "scale", np.float16), m["cols"])
    return out


def gelu(x):
    from math import sqrt
    import scipy.special as sp
    return 0.5 * x * (1.0 + sp.erf(x / sqrt(2.0)))


def layer_norm(x, w, b, eps=1e-12):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


def embed(ids: list[int], W: dict) -> np.ndarray:
    L = len(ids)
    x = W["word"][ids] + W["pos"][:L] + W["type0"][0]
    x = layer_norm(x, W["emb_ln.w"], W["emb_ln.b"])
    for i in range(6):
        p = f"encoder.layer.{i}."
        q = x @ W[p + "attention.self.query.w"].T + W[p + "attention.self.query.b"]
        k = x @ W[p + "attention.self.key.w"].T + W[p + "attention.self.key.b"]
        v = x @ W[p + "attention.self.value.w"].T + W[p + "attention.self.value.b"]
        qh, kh, vh = (a.reshape(L, 12, 32).transpose(1, 0, 2) for a in (q, k, v))
        sc = qh @ kh.transpose(0, 2, 1) / np.sqrt(32.0)
        sc = sc - sc.max(-1, keepdims=True)
        pr = np.exp(sc)
        pr /= pr.sum(-1, keepdims=True)
        ctx = (pr @ vh).transpose(1, 0, 2).reshape(L, 384)
        x = layer_norm(x + ctx @ W[p + "attention.output.dense.w"].T + W[p + "attention.output.dense.b"], W[p + "attention.output.LayerNorm.w"], W[p + "attention.output.LayerNorm.b"])
        h = gelu(x @ W[p + "intermediate.dense.w"].T + W[p + "intermediate.dense.b"])
        x = layer_norm(x + h @ W[p + "output.dense.w"].T + W[p + "output.dense.b"], W[p + "output.LayerNorm.w"], W[p + "output.LayerNorm.b"])
    e = x.mean(0)
    return e / np.linalg.norm(e)


if __name__ == "__main__":
    samples = ["How often is the data updated?", "worth a look meaning", "can i downlod india file", "What does the product card not show?", "Is the data free?", "packsense kya hai",
               "Why does Open Food Facts keep 11 simple checks on nutrition numbers?"]
    full = st.encode(samples, normalize_embeddings=True)
    ref = {"samples": samples, "ids": [pruned_ids(s) for s in samples]}
    for bits in (8, 4):
        W = load(bits)
        E = np.stack([embed(pruned_ids(s), W) for s in samples])
        cos = (E * full).sum(1)
        print(f"int{bits}: cosine to the original MiniLM embeddings on the samples: min {cos.min():.4f}, mean {cos.mean():.4f}")
        ref[f"int{bits}"] = np.round(E, 6).tolist()
    (OUT / "reference.json").write_text(json.dumps(ref), encoding="utf-8")
    import gzip
    print("\nfiles written to", OUT)
    for f in sorted(OUT.iterdir()):
        raw = f.stat().st_size
        gz = len(gzip.compress(f.read_bytes(), 6))
        print(f"  {f.name:24s} {raw/1e6:8.3f} MB   gzip {gz/1e6:8.3f} MB")
