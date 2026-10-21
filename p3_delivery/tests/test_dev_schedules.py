"""Development mode does not pause a job whose file says `pause_status: UNPAUSED` (found 2026-10-20: the dev copies of bronze, gold and archive ran on
their schedules every day). Each dev copy is paused by name in the target; this keeps all four in step and keeps production untouched."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROOT_BUNDLE = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
GOLD_BUNDLE = yaml.safe_load((ROOT / "p4_modelling" / "databricks.yml").read_text(encoding="utf-8"))


def test_every_dev_job_of_the_main_bundle_is_paused_by_name():
    jobs = ROOT_BUNDLE["targets"]["dev"]["resources"]["jobs"]
    assert set(jobs) == {"bronze_load", "archive", "snapshots", "reconcile_candidates", "reconcile_load", "reconcile_lookup", "egress_check"}
    assert all(j["schedule"]["pause_status"] == "PAUSED" for j in jobs.values())


def test_the_dev_gold_job_is_paused_by_name():
    assert GOLD_BUNDLE["targets"]["dev"]["resources"]["jobs"]["gold_build"]["schedule"]["pause_status"] == "PAUSED"


def test_the_paused_names_match_real_jobs_and_production_overrides_nothing():
    defined = set()
    for f in (ROOT / "p3_delivery" / "resources").glob("*.yml"):
        defined |= set(yaml.safe_load(f.read_text(encoding="utf-8"))["resources"]["jobs"])
    assert set(ROOT_BUNDLE["targets"]["dev"]["resources"]["jobs"]) <= defined
    gold = set(yaml.safe_load((ROOT / "p4_modelling" / "resources" / "gold_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"])
    assert set(GOLD_BUNDLE["targets"]["dev"]["resources"]["jobs"]) <= gold
    assert "resources" not in ROOT_BUNDLE["targets"]["prod"] and "resources" not in GOLD_BUNDLE["targets"]["prod"]
    for f in (ROOT / "p3_delivery" / "resources").glob("*.yml"):          # the production schedules stay as they are
        for job in yaml.safe_load(f.read_text(encoding="utf-8"))["resources"]["jobs"].values():
            assert job["schedule"]["pause_status"] == "UNPAUSED"
