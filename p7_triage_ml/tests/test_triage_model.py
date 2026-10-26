"""The parts of the triage run that do not need scikit-learn, on real rows from the feature slice (labels are planted where the real slice has none),
and a check of the notebook's guards. The model fit itself runs only where scikit-learn is installed (Databricks)."""
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import test_triage_features as ttf  # noqa: E402
import triage_eval as te  # noqa: E402
import triage_features as tf  # noqa: E402
import triage_model as tm  # noqa: E402


def _real_rows():
    cur = ttf._con().execute(tf.training_sql(1, engine="duckdb"))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["snapshot_date"] = str(r["snapshot_date"])
        r["outcome"] = "positive" if (r["n_open_flags"] or 0) >= 4 else "negative"           # planted: the slice has no event table
    return rows


ROWS = _real_rows()


def test_the_matrix_has_one_row_per_flag_nan_for_missing_values_and_the_family_last():
    levels = tm.family_levels(ROWS)
    x, y = tm.build_matrix(ROWS, with_family=True, levels=levels)
    assert len(x) == len(y) == len(ROWS) and all(len(r) == len(tm.NUMERIC) + 1 for r in x)
    assert any(math.isnan(v) for r in x for v in r[:-1]) and sum(y) == sum(1 for r in ROWS if r["outcome"] == "positive") > 0
    fam = [r[-1] for r in x]
    assert all(int(f) == levels.index(r["family"]) for f, r in zip(fam, ROWS))
    x2, _ = tm.build_matrix(ROWS, with_family=False, levels=levels)
    assert all(len(r) == len(tm.NUMERIC) for r in x2)
    unseen, _ = tm.build_matrix([{**ROWS[0], "family": "a-family-no-training-row-had"}], with_family=True, levels=levels)
    assert unseen[0][-1] == len(levels)                                                  # the shared (other) level


def test_the_family_levels_are_the_most_common_training_families_and_capped(monkeypatch):
    levels = tm.family_levels(ROWS)
    counts = {}
    for r in ROWS:
        counts[r["family"]] = counts.get(r["family"], 0) + 1
    assert levels[0] == max(counts, key=lambda f: (counts[f], f)) or counts[levels[0]] == max(counts.values())
    assert set(levels) == set(counts)
    monkeypatch.setattr(tm, "MAX_FAMILIES", 2)
    assert tm.family_levels(ROWS) == levels[:2]


def test_the_freeze_hash_follows_the_code_the_configuration_and_the_weeks():
    hashes = tm.code_hashes()
    assert set(hashes) == set(tm.CODE_FILES) and all(len(h) == 64 for h in hashes.values())
    weeks = te.split_weeks(list(range(10)), 4, 3)
    base = tm.freeze_record(tm.Config(), weeks, hashes)
    assert base == tm.freeze_record(tm.Config(), weeks, hashes)
    assert base["freeze_hash"] != tm.freeze_record(tm.Config(steps=2), weeks, hashes)["freeze_hash"]
    assert base["freeze_hash"] != tm.freeze_record(tm.Config(max_iter=201), weeks, hashes)["freeze_hash"]
    assert base["freeze_hash"] != tm.freeze_record(tm.Config(), te.split_weeks(list(range(11)), 4, 3), hashes)["freeze_hash"]
    changed = {**hashes, "triage_labels.py": "0" * 64}
    assert base["freeze_hash"] != tm.freeze_record(tm.Config(), weeks, changed)["freeze_hash"]


def test_a_final_measurement_is_allowed_once_per_freeze_hash():
    assert tm.final_allowed("abc", [])
    assert tm.final_allowed("abc", ["xyz"])
    assert not tm.final_allowed("abc", ["xyz", "abc"])


def test_the_report_covers_the_uncovered_flags_first_and_reduces_k_when_there_are_too_few():
    uncovered = [r for r in ROWS if te.rules_lib.rule_for_family(r["family"]) is None]
    assert len(uncovered) > 50
    perfect = [1.0 if r["outcome"] == "positive" else 0.0 for r in ROWS]
    weak = [0.5] * len(ROWS)
    rep = tm.evaluate(ROWS, {"model_without_family": weak, "model_with_family": perfect}, k=30)
    head = rep["uncovered"]
    assert head["rows"] == len(uncovered) and head["k"] == 30 and not head["k_reduced"]
    assert set(head["systems"]) == {"random", "severity", "rule_family", "model_without_family", "model_with_family"}
    assert head["systems"]["model_with_family"]["precision"] == 1.0 and rep["kill_rule"]["model_precision"] == 1.0
    big = tm.evaluate(ROWS, {"model_with_family": perfect}, k=10_000)
    assert big["uncovered"]["k_reduced"] and big["uncovered"]["k"] == len(uncovered)
    json_safe = tm.jsonable({"a": float("nan"), "b": [float("inf"), 1.5], "c": {"d": 2}})
    assert json_safe == {"a": None, "b": [None, 1.5], "c": {"d": 2}}


def test_the_notebook_never_reads_the_test_weeks_outside_the_final_mode():
    text = (HERE.parent / "notebooks" / "triage_run.py").read_text(encoding="utf-8")
    assert "scikit-learn==1.9.1" in text
    dev = text[text.index('if MODE == "dev":'):text.index("record = tm.freeze_record(")]
    assert 'split["test"]' not in dev and "split['test']" not in dev
    final = text[text.index("# final"):]
    order = [final.index("FREEZE_HASH != record"), final.index("tm.final_allowed"), final.index("run_models(train, test"), final.rindex("saveAsTable")]
    assert order == sorted(order)                                                        # the guards come before the training, the record after
    assert 'if MODE not in ("smoke", "dev", "freeze", "final")' in text


def test_the_model_fit_runs_where_scikit_learn_is_installed():
    pytest.importorskip("sklearn")
    np = pytest.importorskip("numpy")
    x, y = tm.build_matrix(ROWS, with_family=True, levels=tm.family_levels(ROWS))
    scores = tm.fit_scores(np.asarray(x), np.asarray(y), np.asarray(x), tm.Config(max_iter=20, min_samples_leaf=5), with_family=True)
    assert len(scores) == len(ROWS) and all(0.0 <= s <= 1.0 for s in scores)
