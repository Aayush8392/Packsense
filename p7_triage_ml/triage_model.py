"""The flag-triage model and the way it is run (roadmap Phase D item 17).

The owner's method, enforced by code: develop on a few weeks (`dev`), FREEZE (the code hashes, the configuration and the weeks are written down and
get one hash), and measure on the test weeks ONCE (`final` refuses to run for a freeze hash that already has a final result). The kill rule is in
`triage_eval.kill_rule`. Nothing leaves Databricks except counts and precision figures.

This module is plain Python so it can be tested without scikit-learn; `fit_scores` imports scikit-learn when it is called (the notebook installs
scikit-learn 1.9.1, released 2026-09-10).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import rules_lib
import triage_eval as te

NUMERIC = ("flag_age", "n_open_flags", "n_open_errors", "edited_since_prev", "days_since_edit", "n_categories", "n_nutrients", "max_mass_g",
           "energy_kj", "energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars", "proteins", "salt", "sodium", "fiber")
MAX_FAMILIES = 200                       # scikit-learn's categorical limit is 255; the rest share one level
OTHER = "(other)"
CODE_FILES = ("triage_labels.py", "triage_features.py", "triage_eval.py", "triage_model.py")


@dataclass(frozen=True)
class Config:
    """Everything that decides a run. Changing any field changes the freeze hash."""
    steps: int = 4                        # the label window, in snapshots (2, 4 and 8 are reported; 4 is the headline)
    severity: str = "error"               # the model's population
    n_test_weeks: int = 3
    k: int = te.HEADLINE_K
    seed: int = 20261026
    max_iter: int = 200
    learning_rate: float = 0.05
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 100
    l2_regularization: float = 1.0
    extra: dict = field(default_factory=dict)

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def code_hashes(folder: Path | str | None = None) -> dict[str, str]:
    base = Path(folder) if folder else Path(__file__).resolve().parent
    return {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in CODE_FILES}


def freeze_record(config: Config, weeks: dict, hashes: dict[str, str]) -> dict:
    """The record written at the freeze. `weeks` is the output of `triage_eval.split_weeks`. The hash covers the code, the configuration and the weeks."""
    body = {"config": json.loads(config.canonical()), "weeks": {k: list(map(int, v)) for k, v in weeks.items()}, "code": hashes}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**body, "freeze_hash": digest}


def final_allowed(freeze_hash: str, finished: list[str]) -> bool:
    """A final measurement is allowed once per freeze hash."""
    return freeze_hash not in set(finished)


# --- the matrix ---------------------------------------------------------------------------------------------------------------------------

def family_levels(train_rows: list[dict]) -> list[str]:
    """The most common families of the TRAINING rows, at most MAX_FAMILIES; a test family outside the list shares the (other) level."""
    counts: dict[str, int] = {}
    for r in train_rows:
        counts[r["family"]] = counts.get(r["family"], 0) + 1
    return [f for f, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_FAMILIES]]


def build_matrix(rows: list[dict], with_family: bool, levels: list[str]) -> tuple[list[list[float]], list[int]]:
    """Feature rows (NaN for a missing value) and 0/1 labels. The family comes last, as an index into `levels` (len(levels) means (other))."""
    index = {f: i for i, f in enumerate(levels)}
    nan = float("nan")
    x, y = [], []
    for r in rows:
        vals = [nan if r.get(c) is None else float(r[c]) for c in NUMERIC]
        if with_family:
            vals.append(float(index.get(r["family"], len(levels))))
        x.append(vals)
        y.append(1 if r["outcome"] == "positive" else 0)
    return x, y


def fit_scores(x_train, y_train, x_test, config: Config, with_family: bool) -> list[float]:
    """Train on the training rows and score the test rows (probability of a fix). Needs numpy and scikit-learn."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    cat = [True if (with_family and i == len(NUMERIC)) else False for i in range(len(x_train[0]))]
    model = HistGradientBoostingClassifier(
        max_iter=config.max_iter, learning_rate=config.learning_rate, max_leaf_nodes=config.max_leaf_nodes, min_samples_leaf=config.min_samples_leaf,
        l2_regularization=config.l2_regularization, random_state=config.seed, categorical_features=cat if any(cat) else None, early_stopping=False)
    model.fit(np.asarray(x_train, dtype=float), np.asarray(y_train))
    return [float(p) for p in model.predict_proba(np.asarray(x_test, dtype=float))[:, 1]]


# --- the report ---------------------------------------------------------------------------------------------------------------------------

def _row_id(r: dict) -> str:
    return f"{r['snapshot_date']}|{r['code']}|{r['severity']}|{r['flag']}"


def evaluate(test_rows: list[dict], model_scores: dict[str, list[float]], k: int) -> dict:
    """`test_rows` are the labelled test rows (outcome positive or negative) with their `family`; `model_scores` maps a system name to one score per row,
    in row order. The headline is the uncovered ERROR flags; the whole error population and the covered flags are reported next to it.
    If fewer than k rows are uncovered, k is reduced to the number of rows and the report says so."""
    rows = [{"id": _row_id(r), "severity": r["severity"], "family": r["family"], "label": 1 if r["outcome"] == "positive" else 0, "snapshot_date": r["snapshot_date"]}
            for r in test_rows]
    systems = {"random": te.random_scores(rows), "severity": te.severity_scores(rows), "rule_family": te.rule_scores(rows)}
    for name, scores in model_scores.items():
        systems[name] = {r["id"]: s for r, s in zip(rows, scores)}
    report = {"rows": len(rows), "positives": sum(r["label"] for r in rows)}
    for part, subset in (("uncovered", te.uncovered(rows)), ("all", rows), ("covered", [r for r in rows if rules_lib.rule_for_family(r["family"])])):
        kk = min(k, len(subset)) if subset else 0
        report[part] = {"rows": len(subset), "positives": sum(r["label"] for r in subset), "k": kk, "k_reduced": kk < k,
                        "systems": {n: te.precision_at_k(subset, s, kk) if kk else None for n, s in systems.items()}}
    head = report["uncovered"]["systems"]
    if report["uncovered"]["k"]:
        baselines = {n: head[n] for n in ("random", "severity", "rule_family")}
        model = head.get("model_with_family")
        report["kill_rule"] = te.kill_rule(model, baselines) if model else None
    return report


def jsonable(obj):
    """NaN and infinity are not JSON: replace them so a report can be written."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def matrix_from_frame(df, with_family: bool, levels: list[str]):
    """The same matrix as `build_matrix`, straight from a pandas frame with numpy (millions of rows do not fit in Python lists). Needs pandas and numpy."""
    import numpy as np
    x = df[list(NUMERIC)].astype(float).to_numpy()
    if with_family:
        index = {f: i for i, f in enumerate(levels)}
        fam = df["family"].map(lambda f: index.get(f, len(levels))).to_numpy(dtype=float)
        x = np.column_stack([x, fam])
    y = (df["outcome"] == "positive").to_numpy(dtype=int)
    return x, y
