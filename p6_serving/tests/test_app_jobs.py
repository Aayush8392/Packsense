"""The app's list of pipeline jobs (src/data/jobs.json) stays in step with the collector that writes pipeline_health."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p9_operations"))
import health_lib  # noqa: E402

JOBS = json.loads((ROOT / "p6_serving" / "app" / "src" / "data" / "jobs.json").read_text(encoding="utf-8"))


def test_the_app_lists_exactly_the_jobs_the_collector_reports():
    assert {job["name"] for job in JOBS} == set(health_lib.JOB_NAMES)
    assert len(JOBS) == len(health_lib.JOB_NAMES)


def test_every_job_has_a_known_cadence_and_only_the_daily_load_names_a_time():
    for job in JOBS:
        assert job["cadence"] in {"daily", "weekly", "monthly"}, job
    assert [job["name"] for job in JOBS if "at" in job] == ["packsense-bronze-load"]
