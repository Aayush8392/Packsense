"""A learned "answer or not" rule (Phase C item 14). Replaces the two fixed thresholds (best score at least 0.60, lead of at least 0.06) with the probability, from a small
logistic model, that answering with the best entry is right. The model has a handful of weights, so it runs in the browser as a dot product and a sigmoid.

Features of the best entry: blended score, lead over the best rival with a different answer, its keyword score and its embedding score, where it ranks in each of those two lists,
the number of meaningful words in the question, and the number of words the catalogue has never seen.
"""
from __future__ import annotations

import numpy as np

import matcher as mt
import trial_embeddings as te

NAMES = ["bias", "score", "lead", "lex", "emb", "lex_rank", "emb_rank", "words", "unknown", "agree"]


class AbstainMatcher(te.HybridMatcher):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.w: np.ndarray | None = None
        self.mu = np.zeros(len(NAMES))
        self.sd = np.ones(len(NAMES))
        self.tau = 0.7
        self.p_override: dict[str, float] = {}
        self._last = None

    def scores(self, query, skip_wording=None):
        self._last = (query, skip_wording)
        return super().scores(query, skip_wording)

    def features(self, query: str, top_id: str, top: float, rival: float) -> np.ndarray:
        lex, best = self._parts[self._last]
        lex_order = sorted(lex, key=lambda i: -lex[i])
        emb_order = sorted(best, key=lambda i: -best[i])
        lr = lex_order.index(top_id) if top_id in lex_order else 9
        er = emb_order.index(top_id) if top_id in emb_order else 9
        words = min(len(mt.tokens(query)), 12)
        unknown = min(self.unknown_words(query), 3)
        agree = float(lr == 0 and er == 0)
        return np.array([1.0, top, top - rival, lex.get(top_id, 0.0), best.get(top_id, 0.0), min(lr, 5), min(er, 5), words, unknown, agree])

    def probability(self, query: str, top_id: str, top: float, rival: float) -> float:
        if query in self.p_override:
            return self.p_override[query]
        x = (self.features(query, top_id, top, rival) - self.mu) / self.sd
        x[0] = 1.0
        return float(1 / (1 + np.exp(-(self.w @ x))))

    def is_clear(self, top_id, top, rival, query):
        if self.w is None and not self.p_override:
            return super().is_clear(top_id, top, rival, query)
        return self.probability(query.strip(), top_id, top, rival) >= self.tau


def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, steps: int = 400):
    """Logistic regression by Newton steps on standardised features. Returns (weights, mean, std)."""
    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-6] = 1.0
    mu[0], sd[0] = 0.0, 1.0
    Z = (X - mu) / sd
    w = np.zeros(Z.shape[1])
    reg = l2 * np.eye(Z.shape[1])
    reg[0, 0] = 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(Z @ w)))
        grad = Z.T @ (p - y) + reg @ w
        hess = (Z * (p * (1 - p))[:, None]).T @ Z + reg + 1e-6 * np.eye(Z.shape[1])
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w, mu, sd
