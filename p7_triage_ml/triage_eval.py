"""How the flag-triage model is judged (roadmap Phase D item 17; the kill rule was set by the owner on 2026-10-26, before any model run).

The headline: precision@1,000 on the 4-snapshot label among ERROR flags that our rules do not cover (`rules_lib.rule_for_family` is None).
PASS when the model beats the best baseline AND the lower end of the model's 95% Wilson interval is above that baseline's point estimate.
FAIL otherwise, and then only the baseline ranking and the coverage table are published (design 7.2). Whatever the result, no precision@k from
HUMAN labels is published unless the labelling gate passes (that is a separate rule, item 16).

Baselines, in the agreed order: random, OFF severity, rule-decided family, then the model without and with the flag-family features.

Everything here is plain Python on rows shaped {"id", "severity", "family", "label": 1 or 0, "week": snapshot index} and a score per id. Ties are broken by
a hash of the id so a ranking never depends on row order.
"""
from __future__ import annotations

import hashlib
import math

import rules_lib

HEADLINE_K = 1000
Z95 = 1.959964


def tie_key(row_id: str) -> str:
    return hashlib.md5(str(row_id).encode("utf-8")).hexdigest()


def rank(scores: dict[str, float]) -> list[str]:
    """Ids from the highest score to the lowest; equal scores in a fixed, row-order-free order."""
    return sorted(scores, key=lambda i: (-scores[i], tie_key(i)))


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for a proportion. (0.0, 1.0) when n is 0."""
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def precision_at_k(rows: list[dict], scores: dict[str, float], k: int) -> dict:
    """Precision among the k highest-scored rows (fewer when there are fewer rows), with its Wilson interval and the base rate of the whole set."""
    by_id = {r["id"]: r for r in rows}
    top = rank({i: scores[i] for i in by_id})[:k]
    hits = sum(by_id[i]["label"] for i in top)
    lo, hi = wilson(hits, len(top))
    base = sum(r["label"] for r in rows) / len(rows) if rows else 0.0
    return {"k": len(top), "hits": hits, "precision": hits / len(top) if top else 0.0, "low": lo, "high": hi, "base_rate": base, "rows": len(rows)}


# --- the baselines ------------------------------------------------------------------------------------------------------------------------

SEVERITY_ORDER = {"bug": 3, "error": 2, "warning": 1, "info": 0}


def random_scores(rows: list[dict]) -> dict[str, float]:
    return {r["id"]: 0.0 for r in rows}              # all equal: the hash tie-break IS the random order, the same every time


def severity_scores(rows: list[dict]) -> dict[str, float]:
    return {r["id"]: float(SEVERITY_ORDER.get(r["severity"], 0)) for r in rows}


def rule_scores(rows: list[dict]) -> dict[str, float]:
    """OFF severity first, then flags whose family one of our rules decides (those are the ones that we can check by arithmetic)."""
    return {r["id"]: SEVERITY_ORDER.get(r["severity"], 0) + (0.5 if rules_lib.rule_for_family(r["family"]) else 0.0) for r in rows}


def uncovered(rows: list[dict]) -> list[dict]:
    """The flags no rule of ours decides."""
    return [r for r in rows if rules_lib.rule_for_family(r["family"]) is None]


# --- splitting by time ---------------------------------------------------------------------------------------------------------------------

def split_weeks(weeks: list[int], steps: int, n_test: int) -> dict:
    """Train, purge and test weeks. `weeks` are snapshot indexes that have a label (already without the censored ones), `steps` the label window.
    The last `n_test` weeks are the test set. A training week t is used only if t + steps is at or before the first test week: its label looks that far
    ahead, and a label that reaches into the test weeks would let the future leak into training. The weeks in between are purged, not used."""
    weeks = sorted(set(weeks))
    if n_test < 1 or n_test >= len(weeks):
        raise ValueError("n_test must leave at least one training week")
    test = weeks[-n_test:]
    first_test = test[0]
    train = [w for w in weeks[:-n_test] if w + steps <= first_test]
    purged = [w for w in weeks[:-n_test] if w + steps > first_test]
    return {"train": train, "purged": purged, "test": test}


# --- the kill rule -------------------------------------------------------------------------------------------------------------------------

def kill_rule(model: dict, baselines: dict[str, dict]) -> dict:
    """`model` and each baseline are precision_at_k results on the same rows. PASS needs the model above the best baseline AND the lower end of the model's
    interval above that baseline's point estimate."""
    best_name = max(baselines, key=lambda n: baselines[n]["precision"])
    best = baselines[best_name]
    passed = model["precision"] > best["precision"] and model["low"] > best["precision"]
    return {"passed": passed, "best_baseline": best_name, "baseline_precision": best["precision"], "model_precision": model["precision"],
            "model_low": model["low"], "model_high": model["high"]}
