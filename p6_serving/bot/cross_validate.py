"""5-fold cross-validation on the 150 ChatGPT questions (Phase C item 14): every question is scored by a bot that never saw it.

For each fold, the other four folds ("training") are used ONLY in two automatic ways:
  1. their ON and follow-up questions are added to the catalogue as extra wordings of the entry they were labelled with;
  2. the blend weight, the confidence threshold and the margin are chosen on them (each training question tested without its own wording).
Nothing is written by hand from the test fold's failures. Run from the scratch venv that has sentence-transformers:

    <scratch venv>/Scripts/python.exe p6_serving/bot/cross_validate.py

It prints three results: (A) the catalogue as it is, fixed settings, no additions; (B) additions only; (C) additions and tuned settings. B and C are cross-validated.
A is NOT cross-validated: it was changed by hand (merged duplicates, keyword phrasings) after the questions were read, so read it as optimistic.
"""
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import evaluate_external as ee  # noqa: E402
import matcher as mt  # noqa: E402

K = 5
SEED = "packsense-cv-2026"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FIXED_PARAMS = (0.7, 0.60, 0.06)                       # alpha, confident, margin: the frozen settings
GRID = [(a, t, g) for a in (0.5, 0.7, 0.85) for t in (0.5, 0.6, 0.7) for g in (0.03, 0.06, 0.10)]


def folds(rows: list[dict], k: int = K, seed: str = SEED) -> dict[int, list[dict]]:
    """Stratified by question type, in a fixed hash order, so each fold has the same mix of ON, OFF and follow-up questions."""
    out: dict[int, list[dict]] = {i: [] for i in range(k)}
    for kind in ("ON", "OFF", "NEXT"):
        part = sorted((r for r in rows if r["kind"] == kind), key=lambda r: hashlib.sha256(f"{seed}:{r['n']}".encode()).hexdigest())
        for rank, r in enumerate(part):
            out[rank % k].append(r)
    return out


def with_extra_wordings(entries: list[dict], train: list[dict]) -> list[dict]:
    """A copy of the catalogue in which each training ON / follow-up question is a wording of the entry it was labelled with."""
    es = copy.deepcopy(entries)
    by_id = {e["id"]: e for e in es}
    alias = {e["id"]: e["same_as"] for e in es if e.get("same_as")}
    for r in train:
        if r["kind"] == "OFF" or r["rule"] != "entry" or not (1 <= len(r["accept"]) <= 3):
            continue
        first = r["primary"]                                  # the entry listed first in the label is the best answer
        target = by_id[alias.get(first, first)]
        target["alt"] = list(dict.fromkeys(list(target.get("alt", [])) + [r["text"]]))
    return es


def objective(stats: dict) -> float:
    return sum(s["ok"] for s in stats.values()) - 5 * sum(s["wrong"] for s in stats.values())


def set_params(m, params) -> None:
    m.alpha, mt.CONFIDENT, mt.MARGIN = params
    mt.STRONG = params[1] + 0.15
    mt.LAMBDA, mt.BETA = 0.4, 0.1


def run_cv(entries, fixed, follow, rows, additions: bool, tune: bool):
    import trial_embeddings as te                      # needs sentence-transformers, so it is imported only when a run starts
    fs = folds(rows)
    per_fold, chosen = [], []
    for i in range(K):
        test = fs[i]
        train = [r for j in range(K) if j != i for r in fs[j]]
        es = with_extra_wordings(entries, train) if additions else entries
        m = te.HybridMatcher(MODEL, FIXED_PARAMS[0], es, fixed)
        params = FIXED_PARAMS
        if tune:
            best = None
            for p in GRID:
                set_params(m, p)
                st, _ = ee.score(m, train, follow, loo=True, memory_baseline=False)
                key = (objective(st), -abs(p[0] - 0.7))
                if best is None or key > best[0]:
                    best = (key, p)
            params = best[1]
        set_params(m, params)
        st, bad = ee.score(m, test, follow, loo=False, memory_baseline=True)
        per_fold.append(st)
        chosen.append(params)
    return ee.merge(per_fold), chosen


def main() -> None:
    import trial_embeddings as te
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    rows = ee.load()
    m = te.HybridMatcher(MODEL, FIXED_PARAMS[0], entries, fixed)
    set_params(m, FIXED_PARAMS)
    stats, _ = ee.score(m, rows, follow)
    ee.report(stats, "A. catalogue as it is now, fixed settings, no additions (not cross-validated; optimistic):")
    sb, _ = run_cv(entries, fixed, follow, rows, additions=True, tune=False)
    ee.report(sb, "B. 5-fold cross-validation: + training questions as extra wordings, fixed settings:")
    sc, chosen = run_cv(entries, fixed, follow, rows, additions=True, tune=True)
    ee.report(sc, "C. 5-fold cross-validation: + extra wordings + settings tuned on the training folds:")
    print("  settings chosen per fold (blend weight, confident, margin):", chosen)


if __name__ == "__main__":
    main()
