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


# --- weekly scoring -----------------------------------------------------------------------------------------------------------------------------

def _reg(version, stage, dates, created="2026-11-03"):
    return {"version": version, "stage": stage, "train_snapshots": dates, "created_at": created}


def test_the_weekly_run_scores_with_the_production_and_the_measured_version_and_refuses_a_registry_without_production():
    rows = [_reg(1, "measured_reference", '["2026-07-26"]'), _reg(2, "production", '["2026-03-22"]'), _reg(3, "archived", '["2026-03-22"]')]
    assert [v["version"] for v in tx.live_versions(rows)] == [2, 1] or [v["version"] for v in tx.live_versions(rows)] == [1, 2]
    assert {v["stage"] for v in tx.live_versions(rows)} == {"production", "measured_reference"}
    with pytest.raises(RuntimeError, match="no production"):
        tx.live_versions([_reg(1, "measured_reference", '["2026-07-26"]')])
    assert [v["version"] for v in tx.live_versions([_reg(2, "production", '["2026-03-22"]')])] == [2]


def test_each_version_is_scored_with_features_built_from_its_own_first_training_snapshot():
    assert tx.from_date_of(_reg(1, "measured_reference", '["2026-08-09", "2026-07-26", "2026-08-02"]')) == "2026-07-26"
    assert tx.from_date_of(_reg(2, "production", ["2026-04-05", "2026-03-22"])) == "2026-03-22"


def test_the_score_stats_row_has_the_distribution_the_counts_and_the_missing_shares_of_every_feature():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([{c: (None if (i + j) % 3 == 0 else float(i)) for j, c in enumerate(tm.NUMERIC)} for i in range(30)])
    shares = tx.missing_shares(df)
    assert set(shares) == set(tm.NUMERIC) and all(0.0 <= v <= 1.0 for v in shares.values())
    scores = [i / 100 for i in range(100)]
    row = tx.stats_row(dt.date(2026, 11, 1), {"version": 2, "stage": "production"}, scores, [str(i % 40) for i in range(100)], shares, NOW)
    assert row[:5] == (dt.date(2026, 11, 1), 2, "production", 100, 40) and row[5] == pytest.approx(0.495) and row[6] == 0.5 and row[7] == 0.9 and row[8] == 0.99
    assert json_loads(row[9]).keys() == set(tm.NUMERIC)
    empty = tx.stats_row(dt.date(2026, 11, 1), {"version": 1, "stage": "measured_reference"}, [], [], {}, NOW)
    assert empty[3] == 0 and empty[5] is None and empty[6] is None


def json_loads(text):
    import json
    return json.loads(text)


def test_the_scores_tables_have_the_columns_the_notebook_writes():
    ddl = lambda sql: [c.split()[0] for c in re.search(r"\((.*)\) USING", sql.format(schema="s"), re.S).group(1).replace("\n", " ").split(",") if c.strip()]   # noqa: E731
    assert tuple(ddl(tx.SCORES_DDL)) == tx.SCORES_COLUMNS
    text = (HERE.parent / "notebooks" / "triage_score.py").read_text(encoding="utf-8")
    for col in tx.SCORES_COLUMNS:
        assert col.replace("snapshot_date", "snapshot_date") in text
    assert "delete from" in text and "tx.load_bundle(v[\"path\"], v[\"file_sha256\"])" in text and "from_date_of" in text


def test_the_job_runs_the_scoring_after_open_flags_and_the_deployer_may_read_the_model_files():
    import yaml
    root = HERE.parents[1]
    job = yaml.safe_load((root / "p3_delivery" / "resources" / "snapshots_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["snapshots"]
    tasks = {t["task_key"]: t for t in job["tasks"]}
    assert tasks["score"]["depends_on"] == [{"task_key": "open_flags"}] and "run_if" not in tasks["score"]            # default: only if open_flags succeeded
    assert tasks["score"]["notebook_task"]["notebook_path"].endswith("p7_triage_ml/notebooks/triage_score.py")
    grants = yaml.safe_load((root / "p5_governance" / "grants.yml").read_text(encoding="utf-8"))["securables"]
    vol = [g for g in grants if g.get("name") == "workspace.packsense_snapshots.models"][0]
    assert vol["type"] == "volume" and vol["grants"] == {"packsense-deployer": ["READ_VOLUME"]}
    assert "p7_triage_ml/**" in (root / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")


def test_the_pre_registered_measurement_is_in_the_notebook_and_the_public_page_holds_no_measured_figures():
    doc = (HERE.parent / "REGISTRY.md").read_text(encoding="utf-8")
    nb = (HERE.parent / "notebooks" / "triage_run.py").read_text(encoding="utf-8")
    assert "last_week=12" in doc and "from_date=2026-07-26" in doc and 'dbutils.widgets.text("last_week"' in nb and 'df["week"] <= int(dbutils.widgets.get("last_week"))' in nb
    for fixed in ("Training weeks 0 to 6", "Purged weeks 7 to 9", "Test weeks 10 to 12", "Measured once", "Correction of 2026-11-03"):
        assert fixed in doc
    assert not re.search(r"\d\.\d\s?%|precision of \d|hits", doc)               # the figures are the owner's, not the repository's
    cfg = tm.Config()
    assert cfg.steps == 4 and cfg.n_test_weeks == 3 and cfg.k == 1000                 # the page says window 4, three test weeks, top 1,000


def test_a_week_without_a_positive_label_cannot_be_a_training_week():
    counts = {0: 0, 1: 0, 2: 374, 3: 1420, 4: 1421}
    tx.require_positives(counts, [3, 4])                                              # the weeks with labels are accepted
    with pytest.raises(RuntimeError, match=r"weeks \[0, 1\] have no positive"):
        tx.require_positives(counts, [0, 1, 2, 3])
    with pytest.raises(RuntimeError, match=r"\[7\]"):
        tx.require_positives(counts, [3, 7])                                         # a week missing from the counts has none either
    text = (HERE.parent / "notebooks" / "triage_run.py").read_text(encoding="utf-8")
    assert text.count("tx.require_positives(positives_by_week(df)") == 2             # export, and freeze/final/dev through the split
