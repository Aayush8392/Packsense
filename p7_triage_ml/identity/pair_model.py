r"""Small pair model for identity matching (roadmap item 19): a weighted, L2-regularised logistic regression on four cues, in plain Python (no numpy, so it runs in the repo's own environment).

Cues per pair: the name score, the pack-size relation (same / different; unknown is the reference), the nutrition gap (0 when not computable, with a 'missing' indicator), and the overlap of the name words.
Positive = either 'Same product' label. Every pair carries the weight of its stratum, rescaled to a mean of 1 so the regularisation means the same on any training set.
Fixed before any result: 2,000 gradient steps of rate 0.5 on standardised features, L2 strength 1.0 on the weights (not the intercept).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lib as il  # noqa: E402

POSITIVE = {"Same product, same size", "Same product, different size"}
FEATURES = ("name_score", "size_same", "size_different", "gap", "gap_missing", "word_overlap")
STEPS = 2000
RATE = 0.5
L2 = 1.0


def word_overlap(text_a: str, text_b: str) -> float:
    """Share of the words the two names have in common (Jaccard); 0 when both are empty."""
    a, b = set(il.normalise(text_a).split()), set(il.normalise(text_b).split())
    return len(a & b) / len(a | b) if a | b else 0.0


def features(row: dict) -> list[float]:
    gap = row.get("gap")
    return [row["name_score"], 1.0 if row["size"] == "same" else 0.0, 1.0 if row["size"] == "different" else 0.0,
            0.0 if gap is None else gap, 1.0 if gap is None else 0.0, word_overlap(row["text_a"], row["text_b"])]


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def fit(rows: list[dict]) -> dict:
    """Rows need the keys of `features`, 'label' and 'weight'. 'Cannot tell' rows are left out by the caller. Returns the model as plain numbers."""
    x = [features(r) for r in rows]
    y = [1.0 if r["label"] in POSITIVE else 0.0 for r in rows]
    mean_w = sum(r["weight"] for r in rows) / len(rows)
    w = [r["weight"] / mean_w for r in rows]
    k = len(FEATURES)
    mu = [sum(wi * xi[j] for wi, xi in zip(w, x)) / len(x) for j in range(k)]
    sd = [math.sqrt(sum(wi * (xi[j] - mu[j]) ** 2 for wi, xi in zip(w, x)) / len(x)) or 1.0 for j in range(k)]
    z = [[(xi[j] - mu[j]) / sd[j] for j in range(k)] for xi in x]
    beta, b0 = [0.0] * k, 0.0
    n = len(z)
    for _ in range(STEPS):
        grad, g0 = [0.0] * k, 0.0
        for zi, yi, wi in zip(z, y, w):
            e = wi * (_sigmoid(b0 + sum(bj * zj for bj, zj in zip(beta, zi))) - yi)
            g0 += e
            for j in range(k):
                grad[j] += e * zi[j]
        b0 -= RATE * g0 / n
        beta = [bj - RATE * (gj / n + L2 * bj / n) for bj, gj in zip(beta, grad)]
    return {"intercept": b0, "beta": beta, "mean": mu, "sd": sd}


def predict(model: dict, row: dict) -> float:
    z = model["intercept"] + sum(b * (v - m) / s for b, v, m, s in zip(model["beta"], features(row), model["mean"], model["sd"]))
    return _sigmoid(z)
