"""Model files and the custom registry of the flag-triage model (roadmap Phase D item 20, design 7.7).

Why a custom registry: the managed Unity Catalog registry is unusable on Databricks Free Edition. Registering a model creates the entry, then the upload of the model files to the
catalog's managed storage is refused (S3 `AccessDenied` on `PutObject`; reproduced 2026-11-03, the half-made entry was deleted). So a model version is a file in a Unity Catalog volume plus
one row in the Delta table `model_versions`.

This module is NOT one of `triage_model.CODE_FILES`: the freeze hash of a measured model covers those four files, and a change to them would change the identity of the model that was measured.
`fit_model` therefore repeats the training call of `triage_model.fit_scores` instead of changing it; a test (needs scikit-learn) checks that the two give the same predictions.

Plain Python except where scikit-learn, numpy or pandas are named; those are imported when called.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import triage_model as tm

MODEL_NAME = "flag_triage"
STAGES = ("measured_reference", "production", "archived")
REGISTRY_DDL = """CREATE TABLE IF NOT EXISTS {schema}.model_versions (
    model STRING, version INT, stage STRING, recipe_hash STRING, parent_version INT, train_snapshots STRING, n_train_rows BIGINT, n_positives BIGINT,
    config STRING, code_hashes STRING, sklearn_version STRING, path STRING, file_sha256 STRING, metrics STRING, note STRING, approved_by STRING, created_at TIMESTAMP) USING DELTA"""
COLUMNS = ("model", "version", "stage", "recipe_hash", "parent_version", "train_snapshots", "n_train_rows", "n_positives", "config", "code_hashes", "sklearn_version",
           "path", "file_sha256", "metrics", "note", "approved_by", "created_at")


def fit_model(x_train, y_train, config: tm.Config, with_family: bool):
    """The same training as `triage_model.fit_scores`, but the fitted model and the column mask come back. Needs numpy and scikit-learn."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    x_train = np.asarray(x_train, dtype=float)
    keep = ~np.isnan(x_train).all(axis=0)
    x_train = x_train[:, keep]
    family_column = x_train.shape[1] - 1 if with_family else None
    cat = [i == family_column for i in range(x_train.shape[1])]
    model = HistGradientBoostingClassifier(
        max_iter=config.max_iter, learning_rate=config.learning_rate, max_leaf_nodes=config.max_leaf_nodes, min_samples_leaf=config.min_samples_leaf,
        l2_regularization=config.l2_regularization, random_state=config.seed, categorical_features=cat if any(cat) else None, early_stopping=False)
    model.fit(x_train, np.asarray(y_train))
    return model, [bool(k) for k in keep]


def predict(model, keep: list[bool], x) -> list[float]:
    """Probability of a fix for each row of `x` (built with the same family levels and with_family as the training matrix)."""
    import numpy as np
    x = np.asarray(x, dtype=float)[:, np.asarray(keep, dtype=bool)]
    return [float(p) for p in model.predict_proba(x)[:, 1]]


def save_bundle(path: Path | str, model, keep: list[bool], levels: list[str], with_family: bool, config: tm.Config) -> str:
    """Writes one file with the model, the column mask, the family levels and the configuration. Returns the file's sha256."""
    import joblib
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "keep": keep, "levels": levels, "with_family": with_family, "config": json.loads(config.canonical()), "numeric": list(tm.NUMERIC)}, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bundle(path: Path | str, expected_sha256: str | None = None) -> dict:
    """Loads a bundle; refuses a file whose hash is not the one the registry recorded (a pickle is code: only files this project wrote are loaded)."""
    import joblib
    path = Path(path)
    if expected_sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"{path.name}: the file's hash is not the one in the registry")
    return joblib.load(path)


def score_frame(bundle: dict, df) -> list[float]:
    """Scores a pandas frame of open flags (the columns of `triage_model.NUMERIC` and `family`)."""
    x, _ = tm.matrix_from_frame(df.assign(outcome="negative"), bundle["with_family"], bundle["levels"])
    return predict(bundle["model"], bundle["keep"], x)


def registry_row(version: int, stage: str, recipe_hash: str, parent_version: int | None, train_snapshots: list[str], n_train_rows: int, n_positives: int,
                 config: tm.Config, code_hashes: dict, sklearn_version: str, path: str, file_sha256: str, metrics: dict, note: str, approved_by: str, created_at) -> tuple:
    """One `model_versions` row, in the order of COLUMNS. The stage is checked here so a typo cannot reach the table."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}, not {stage!r}")
    if version < 1:
        raise ValueError("a version starts at 1")
    return (MODEL_NAME, int(version), stage, recipe_hash, None if parent_version is None else int(parent_version), json.dumps(sorted(train_snapshots)), int(n_train_rows),
            int(n_positives), config.canonical(), json.dumps(code_hashes, sort_keys=True), sklearn_version, path, file_sha256, json.dumps(metrics, sort_keys=True), note, approved_by, created_at)


def current_stage_rows(rows: list[dict]) -> dict[str, dict]:
    """The registry's answer to 'which version is in which stage': the newest row of each stage wins, an archived version is never returned as live."""
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["version"], str(r["created_at"]))):
        out[r["stage"]] = r
    out.pop("archived", None)
    return out


def recipe_hash(config: tm.Config, train_dates: list[str], code_hashes: dict) -> str:
    """The identity of a trained version: the configuration, the snapshot dates it was trained on and the hashes of the four frozen code files."""
    body = {"config": json.loads(config.canonical()), "train_snapshots": sorted(train_dates), "code": code_hashes}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# --- weekly scoring (item 20) --------------------------------------------------------------------------------------------------------------------

SCORES_DDL = """CREATE TABLE IF NOT EXISTS {schema}.triage_scores (
    snapshot_date DATE, snapshot_sha STRING, code STRING, severity STRING, flag STRING, family STRING, model_version INT, stage STRING, score DOUBLE, scored_at TIMESTAMP) USING DELTA"""
SCORES_COLUMNS = ("snapshot_date", "snapshot_sha", "code", "severity", "flag", "family", "model_version", "stage", "score", "scored_at")
STATS_DDL = """CREATE TABLE IF NOT EXISTS {schema}.triage_score_stats (
    snapshot_date DATE, model_version INT, stage STRING, n_flags BIGINT, n_products BIGINT, score_mean DOUBLE, score_p50 DOUBLE, score_p90 DOUBLE, score_p99 DOUBLE,
    missing_share STRING, scored_at TIMESTAMP) USING DELTA"""
LIVE_STAGES = ("production", "measured_reference")


def live_versions(rows: list[dict]) -> list[dict]:
    """The versions the weekly run scores with: whatever is in `production` and in `measured_reference` (newest of each). Refuses a registry with no production version."""
    live = current_stage_rows(rows)
    if "production" not in live:
        raise RuntimeError("the registry has no production version")
    return [live[s] for s in LIVE_STAGES if s in live]


def from_date_of(version_row: dict) -> str:
    """Each version is scored with features built the way ITS training weeks were: ages count from its first training snapshot, not from the oldest snapshot in the table."""
    dates = json.loads(version_row["train_snapshots"]) if isinstance(version_row["train_snapshots"], str) else list(version_row["train_snapshots"])
    return min(str(d) for d in dates)


def quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def stats_row(snapshot_date, version_row: dict, scores: list[float], codes: list[str], missing_share: dict[str, float], scored_at) -> tuple:
    """One `triage_score_stats` row: how many flags and products were scored, the score distribution, and the share of missing values of each feature."""
    s = sorted(scores)
    return (snapshot_date, int(version_row["version"]), version_row["stage"], len(scores), len(set(codes)), (sum(s) / len(s)) if s else None,
            quantile(s, 0.5), quantile(s, 0.9), quantile(s, 0.99), json.dumps({k: round(v, 4) for k, v in sorted(missing_share.items())}), scored_at)


def missing_shares(df, columns=tm.NUMERIC) -> dict[str, float]:
    return {c: float(df[c].isna().mean()) for c in columns}


def require_positives(positives_by_week: dict[int, int], weeks: list[int]) -> None:
    """Refuses to train on a week without a single positive label. Found 2026-11-03: the flag-event table (the source of the fixed/not-fixed label) starts in July, so the
    weeks before it have only the flags that stayed open and NO positives; training on them teaches the model from survivors only. A week that really has no fixed flag is not a
    plausible week of this data (every labelled week since July has more than a thousand)."""
    empty = [w for w in sorted(weeks) if not positives_by_week.get(w)]
    if empty:
        raise RuntimeError(f"weeks {empty} have no positive labels (the label source does not cover them): they cannot be training weeks")
