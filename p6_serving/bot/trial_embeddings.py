"""Trial of a small embedding model against the lexical matcher (Phase C item 14). NOT part of the project's locked dependencies.

Run it from a throwaway environment that has `sentence-transformers` installed (see the buildlog), on the WORKING set only, leave-one-out:

    <scratch venv>/Scripts/python.exe p6_serving/bot/trial_embeddings.py --model sentence-transformers/all-MiniLM-L6-v2

It compares: the lexical matcher alone (alpha 0), the embedding alone (alpha 1) and blends of the two. The held-out set is never read here.
If the embedding wins, the browser build uses the same model through Transformers.js and is measured again on that path (the two can differ slightly).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import evaluate_matcher as ev  # noqa: E402
import matcher as mt  # noqa: E402
import split_questions as sq  # noqa: E402


def plain(text: str) -> str:
    return re.sub(r"\{[^}]*\}", " ", text).strip()


_MODEL = {}
PREFIX = {"intfloat/e5-small-v2": "query: ", "intfloat/e5-base-v2": "query: "}        # models trained with an instruction prefix
_EMB: dict[tuple[str, str], np.ndarray] = {}


def encode(model_name: str, texts: list[str]) -> np.ndarray:
    """Embeddings with one model load and a cache by text, so a rebuilt matcher (cross-validation) does not re-embed what it has already seen."""
    if model_name not in _MODEL:
        from sentence_transformers import SentenceTransformer
        _MODEL[model_name] = SentenceTransformer(model_name)
    todo = [x for x in dict.fromkeys(plain(t) for t in texts) if (model_name, x) not in _EMB]
    if todo:
        pre = PREFIX.get(model_name, "")
        for x, v in zip(todo, _MODEL[model_name].encode([pre + t for t in todo], normalize_embeddings=True, batch_size=64)):
            _EMB[(model_name, x)] = v
    return np.stack([_EMB[(model_name, plain(t))] for t in texts])


class HybridMatcher(mt.Matcher):
    def __init__(self, model_name: str, alpha: float, entries=None, fixed=None):
        super().__init__(entries, fixed)
        self.model_name = model_name
        self.alpha = alpha
        self.emb = encode(model_name, [w for _, w in self.wordings])
        self._parts: dict[tuple, tuple] = {}

    def scores(self, query: str, skip_wording: str | None = None):
        key = (query, skip_wording)
        if key not in self._parts:                     # the two scores are computed once per question; alpha only changes how they are blended
            lex = dict(super().scores(query, skip_wording))
            sims = self.emb @ encode(self.model_name, [query])[0]
            skip = cat.normalise(skip_wording) if skip_wording else None
            best: dict[str, float] = {}
            for k, (eid, _) in enumerate(self.wordings):
                if skip is not None and self.norm_words[k] == skip:
                    continue
                if sims[k] > best.get(eid, -1.0):
                    best[eid] = float(sims[k])
            self._parts[key] = (lex, best)
        lex, best = self._parts[key]
        self.lex_last = lex                                  # the keyword score of every entry for this question (used to check that a hub or a pair has real word support)
        out = [(eid, self.alpha * best.get(eid, 0.0) + (1 - self.alpha) * lex[eid]) for eid in lex]
        return sorted(out, key=lambda x: -x[1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--alphas", type=float, nargs="*", default=[0.0, 0.5, 0.7, 1.0])
    a = ap.parse_args()
    rows = sq.load(HERE / "questions_working.psv")
    entries, fixed = cat.load_entries(), cat.load_fixed()
    truth = ev.truth_for(rows, entries, {})
    n_all = len(rows)
    for alpha in a.alphas:
        m = HybridMatcher(a.model, alpha, entries, fixed)
        best = None
        grid = [(t, g) for t in (0.3, 0.4, 0.5, 0.6, 0.7) for g in (0.0, 0.03, 0.06, 0.1)]
        table = []
        for t, g in grid:
            mt.CONFIDENT, mt.MARGIN, mt.STRONG = t, g, t + 0.15
            res, _, _ = ev.run(rows, m, truth, True)
            wc = res["wrong_conf"] / n_all
            table.append((t, g, res, wc))
        top3, top1 = table[0][2]["top3"] / table[0][2]["n_ans"], table[0][2]["top1"] / table[0][2]["n_ans"]
        ok = [x for x in table if x[3] <= 0.03]
        best = max(ok, key=lambda x: x[2]["direct"]) if ok else min(table, key=lambda x: x[3])
        t, g, res, wc = best
        print(f"alpha {alpha}: top-3 {100 * top3:.1f}%  top-1 {100 * top1:.1f}%  | best setting threshold {t} margin {g}: answered directly & right "
              f"{100 * res['direct'] / res['n_ans']:.1f}%  declines handled {100 * res['dec_ok'] / res['n_dec']:.0f}%  wrong confident {100 * wc:.1f}%"
              f"{'' if wc <= 0.03 else '  (no setting reached 3%)'}")


if __name__ == "__main__":
    main()
