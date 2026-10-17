"""The bronze job as the Asset Bundle defines it (p3_delivery/resources/bronze_job.yml): bronze, then silver that still runs when bronze
ended red, then the drift check and the taxonomy load."""
from pathlib import Path

import yaml

RESOURCES = Path(__file__).resolve().parents[2] / "p3_delivery" / "resources"
JOB = yaml.safe_load((RESOURCES / "bronze_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["bronze_load"]


def tasks():
    return {t["task_key"]: t for t in JOB["tasks"]}


def test_four_tasks_silver_after_bronze_and_even_if_bronze_failed():
    t = tasks()
    assert list(t) == ["bronze", "silver", "drift", "taxonomy"]
    assert [d["task_key"] for d in t["silver"]["depends_on"]] == ["bronze"] and "depends_on" not in t["bronze"]
    assert t["silver"]["run_if"] == "ALL_DONE"


def test_silver_is_told_how_bronze_ended():
    t = tasks()
    assert t["silver"]["notebook_task"]["base_parameters"]["bronze_result"] == "{{tasks.bronze.result_state}}"


def test_drift_and_taxonomy_run_after_silver_even_if_silver_failed():
    t = tasks()
    for key in ("drift", "taxonomy"):
        assert [d["task_key"] for d in t[key]["depends_on"]] == ["silver"] and t[key]["run_if"] == "ALL_DONE"


def test_drift_is_never_retried_automatically_and_the_others_may_be():
    t = tasks()
    assert t["drift"]["disable_auto_optimization"] is True
    assert all("disable_auto_optimization" not in t[k] for k in ("bronze", "silver", "taxonomy"))


def test_no_task_gets_a_secret_as_a_parameter():
    for task in JOB["tasks"]:
        for name in task["notebook_task"]["base_parameters"]:
            assert not any(w in name.lower() for w in ("token", "password", "key", "hmac")), (task["task_key"], name)


def test_one_run_at_a_time_and_the_schedule_is_unchanged():
    assert JOB["max_concurrent_runs"] == 1
    assert JOB["schedule"]["quartz_cron_expression"] == "0 0 9 * * ?" and JOB["schedule"]["pause_status"] == "UNPAUSED"


def test_the_notebooks_exist_in_the_repo():
    for task in JOB["tasks"]:
        path = (RESOURCES / task["notebook_task"]["notebook_path"]).resolve()
        assert path.exists(), path
