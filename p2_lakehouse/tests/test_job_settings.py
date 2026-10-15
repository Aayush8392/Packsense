"""The job definition the bootstrap script would create: bronze, then silver that still runs when bronze ended red, then the drift check."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("databricks.sdk")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import create_bronze_job as job  # noqa: E402


def tasks(with_schedule=True):
    return {t.task_key: t for t in job.settings(with_schedule)["tasks"]}


def test_three_tasks_silver_after_bronze_and_even_if_bronze_failed():
    t = tasks()
    assert list(t) == ["bronze", "silver", "drift"]
    assert [d.task_key for d in t["silver"].depends_on] == ["bronze"] and t["bronze"].depends_on is None
    assert t["silver"].run_if.value == "ALL_DONE"


def test_silver_is_told_how_bronze_ended_and_both_read_the_notebooks_from_git():
    t = tasks()
    assert t["silver"].notebook_task.base_parameters["bronze_result"] == "{{tasks.bronze.result_state}}"
    assert t["silver"].notebook_task.notebook_path == "p2_lakehouse/notebooks/silver_load"
    assert t["bronze"].notebook_task.notebook_path == "p2_lakehouse/notebooks/bronze_load"
    assert all(x.notebook_task.source.value == "GIT" for x in t.values())


def test_drift_runs_after_silver_even_if_silver_failed_and_gets_no_data_parameters():
    t = tasks()
    assert [d.task_key for d in t["drift"].depends_on] == ["silver"] and t["drift"].run_if.value == "ALL_DONE"
    assert t["drift"].notebook_task.notebook_path == "p2_lakehouse/notebooks/drift_check"
    assert set(t["drift"].notebook_task.base_parameters) == {"run_id"}


def test_one_run_at_a_time_and_the_schedule_is_unchanged():
    s = job.settings(True)
    assert s["max_concurrent_runs"] == 1
    assert s["schedule"].quartz_cron_expression == "0 0 9 * * ?" and s["schedule"].pause_status.value == "UNPAUSED"
    assert "schedule" not in job.settings(False)


def test_the_notebooks_exist_in_the_repo():
    root = Path(__file__).resolve().parents[2]
    for path in (job.NOTEBOOK, job.SILVER_NOTEBOOK, job.DRIFT_NOTEBOOK):
        assert (root / (path + ".py")).exists(), path
