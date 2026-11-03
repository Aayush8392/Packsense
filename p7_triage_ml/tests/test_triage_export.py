"""The custom registry of the flag-triage model (item 20): the rows, the stages, the recipe hash and, where scikit-learn is installed, that the exported model predicts
exactly like `triage_model.fit_scores`. Real rows come from the feature slice, as in test_triage_model."""
import datetime as dt
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import test_triage_model as ttm  # noqa: E402
import triage_export as tx  # noqa: E402
import triage_model as tm  # noqa: E402

CFG = tm.Config()
HASHES = tm.code_hashes()
NOW = dt.datetime(2026, 11, 3, 10, 0, 0)


def _row(version=1, stage="production", **kw):
    args = dict(version=version, stage=stage, recipe_hash="h", parent_version=None, train_snapshots=["2026-04-05", "2026-03-29"], n_train_rows=10, n_positives=3, config=CFG,
                code_hashes=HASHES, sklearn_version="1.9.1", path="/Volumes/x/flag_triage_v1.joblib", file_sha256="a" * 64, metrics={"measured": None}, note="n", approved_by="o", created_at=NOW)
    args.update(kw)
    return tx.registry_row(**args)


def test_the_registry_row_has_one_value_per_column_of_the_table():
    ddl_columns = [c.split()[0] for c in re.search(r"\((.*)\) USING", tx.REGISTRY_DDL.format(schema="s"), re.S).group(1).replace("\n", " ").split(",") if c.strip()]
    assert tuple(ddl_columns) == tx.COLUMNS and len(_row()) == len(tx.COLUMNS)
    assert _row()[tx.COLUMNS.index("train_snapshots")] == '["2026-03-29", "2026-04-05"]'          # stored sorted


def test_a_stage_that_is_not_one_of_the_three_cannot_reach_the_table():
    for bad in ("prod", "Production", "", "measured"):
        with pytest.raises(ValueError, match="stage"):
            _row(stage=bad)
    with pytest.raises(ValueError, match="version"):
        _row(version=0)


def test_the_recipe_hash_changes_with_the_weeks_the_configuration_and_the_code_and_not_with_their_order():
    a = tx.recipe_hash(CFG, ["2026-04-05", "2026-03-29"], HASHES)
    assert a == tx.recipe_hash(CFG, ["2026-03-29", "2026-04-05"], HASHES)
    assert a != tx.recipe_hash(CFG, ["2026-03-29"], HASHES)
    assert a != tx.recipe_hash(tm.Config(max_iter=201), ["2026-04-05", "2026-03-29"], HASHES)
    assert a != tx.recipe_hash(CFG, ["2026-04-05", "2026-03-29"], {**HASHES, "triage_model.py": "0" * 64})


def test_the_live_version_of_each_stage_is_the_newest_and_an_archived_one_is_never_live():
    rows = [{"version": 1, "stage": "measured_reference", "created_at": "a"}, {"version": 2, "stage": "production", "created_at": "b"},
            {"version": 3, "stage": "production", "created_at": "c"}, {"version": 4, "stage": "archived", "created_at": "d"}]
    live = tx.current_stage_rows(rows)
    assert live["measured_reference"]["version"] == 1 and live["production"]["version"] == 3 and "archived" not in live


def test_this_module_is_not_one_of_the_files_the_freeze_hash_covers():
    assert "triage_export.py" not in tm.CODE_FILES                  # exporting must not change the identity of the measured model


def test_the_notebook_never_overwrites_a_version_and_exports_the_measured_model_only_from_the_frozen_code():
    text = (HERE.parent / "notebooks" / "triage_run.py").read_text(encoding="utf-8")
    assert "a version is never overwritten" in text and 'frozen[0]["code"] != hashes' in text and "has no final measurement" in text
    assert "export_model(df, all_dates)" in text


def test_the_exported_model_predicts_like_the_trained_scores_and_survives_a_round_trip(tmp_path):
    pytest.importorskip("sklearn")
    np = pytest.importorskip("numpy")
    pytest.importorskip("joblib")
    levels = tm.family_levels(ttm.ROWS)
    x, y = tm.build_matrix(ttm.ROWS, with_family=True, levels=levels)
    cfg = tm.Config(max_iter=20, min_samples_leaf=5)
    model, keep = tx.fit_model(x, y, cfg, with_family=True)
    expected = tm.fit_scores(np.asarray(x), np.asarray(y), np.asarray(x), cfg, with_family=True)
    assert tx.predict(model, keep, x) == pytest.approx(expected, abs=1e-12)
    digest = tx.save_bundle(tmp_path / "m.joblib", model, keep, levels, True, cfg)
    bundle = tx.load_bundle(tmp_path / "m.joblib", digest)
    assert tx.predict(bundle["model"], bundle["keep"], x) == pytest.approx(expected, abs=1e-12) and bundle["levels"] == levels
    with pytest.raises(ValueError, match="hash"):
        tx.load_bundle(tmp_path / "m.joblib", "0" * 64)
