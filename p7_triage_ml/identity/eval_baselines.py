r"""Compares the name-only baseline with a frozen multilingual embedding model on the owner's labelled pairs (roadmap item 19, design 7.4). Counts and rates only.

  D:\off-catalogue-platform\_sandbox\identity_env\Scripts\python.exe p7_triage_ml\identity\eval_baselines.py --input D:\off-catalogue-platform\label_studio\packsense_identity\eval_input.SEALED.json
Needs the scratch environment with sentence-transformers (kept on D:, outside the repo). Model, frozen before the run: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, product text = brand + name.
Positive = 'Same product' (either size); 'Cannot tell' pairs are dropped (and, as a sensitivity run, counted as negatives). Every pair carries the weight of its stratum, so the figures describe all candidate pairs.
Metrics: weighted average precision (AP), and weighted recall when the top K candidate pairs by score are kept (K = 5,000 / 10,000 / 20,000 of about 64,000). 'hybrid' (the mean of both scores) is exploratory, not a frozen system.
A 95% interval for each AP comes from 1,000 bootstrap resamples inside each stratum (fixed seed).
"""
import argparse
import json
import random

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
POSITIVE = {"Same product, same size", "Same product, different size"}


def weighted_ap(rows, key):
    rows = sorted(rows, key=lambda r: -r[key])
    tp = fp = ap = 0.0
    total = sum(r["weight"] for r in rows if r["pos"])
    for r in rows:
        if r["pos"]:
            tp += r["weight"]
            ap += r["weight"] * tp / (tp + fp)
        else:
            fp += r["weight"]
    return ap / total if total else float("nan")


def recall_at(rows, key, k):
    rows = sorted(rows, key=lambda r: -r[key])
    total = sum(r["weight"] for r in rows if r["pos"])
    seen = hit = 0.0
    for r in rows:
        if seen + r["weight"] > k:
            hit += r["weight"] * (k - seen) / r["weight"] if r["pos"] else 0.0   # the pair that straddles the cut counts in proportion
            break
        seen += r["weight"]
        hit += r["weight"] if r["pos"] else 0.0
    return hit / total if total else float("nan")


def bootstrap(rows, key, n=1000, seed=7):
    rng = random.Random(seed)
    by = {}
    for r in rows:
        by.setdefault(r["stratum"], []).append(r)
    vals = []
    for _ in range(n):
        sample = [r for lst in by.values() for r in (rng.choice(lst) for _ in lst)]
        vals.append(weighted_ap(sample, key))
    vals.sort()
    return vals[int(0.025 * n)], vals[int(0.975 * n)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    a = ap.parse_args(argv)
    data = json.load(open(a.input, encoding="utf-8"))
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL)
    rows = data["rows"]
    texts = sorted({t for r in rows for t in (r["text_a"], r["text_b"])})
    emb = dict(zip(texts, model.encode(texts, normalize_embeddings=True, show_progress_bar=False)))
    for r in rows:
        r["embed"] = float(sum(x * y for x, y in zip(emb[r["text_a"]], emb[r["text_b"]])))
        r["hybrid"] = (r["name_score"] + r["embed"]) / 2
        r["pos"] = r["label"] in POSITIVE
    n_drop = sum(1 for r in rows if r["label"] == "Cannot tell")
    for title, use in (("'Cannot tell' dropped", [r for r in rows if r["label"] != "Cannot tell"]), ("'Cannot tell' counted as not matching", rows)):
        print(f"\n== {title}: {len(use)} labelled pairs ({n_drop} cannot-tell in the file); weighted match total {sum(r['weight'] for r in use if r['pos']):.0f} of {sum(r['weight'] for r in use):.0f} candidate pairs")
        print(f"{'score':<12}{'AP':>7}{'95% interval':>16}{'recall@5k':>11}{'@10k':>8}{'@20k':>8}")
        for key, name in (("name_score", "name-only"), ("embed", "embedding"), ("hybrid", "hybrid (exploratory)")):
            lo, hi = bootstrap(use, key)
            print(f"{name:<22}{weighted_ap(use, key):>5.3f}   {lo:.3f} to {hi:.3f}{recall_at(use, key, 5000):>9.3f}{recall_at(use, key, 10000):>8.3f}{recall_at(use, key, 20000):>8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
