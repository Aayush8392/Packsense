"""The bronze job as the Asset Bundle defines it (p3_delivery/resources/bronze_job.yml): the capture first (since 2026-10-18), then bronze
(which still runs when the capture failed), then silver that still runs when bronze ended red, then the drift check and the taxonomy load."""
from pathlib import Path

import yaml

RESOURCES = Path(__file__).resolve().parents[2] / "p3_delivery" / "resources"
JOB = yaml.safe_load((RESOURCES / "bronze_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["bronze_load"]


def tasks():
    return {t["task_key"]: t for t in JOB["tasks"]}


def test_five_tasks_capture_first_and_every_later_task_runs_even_if_the_one_before_failed():
    t = tasks()
    assert list(t) == ["capture", "bronze", "silver", "drift", "taxonomy"]
    assert "depends_on" not in t["capture"]
    assert [d["task_key"] for d in t["bronze"]["depends_on"]] == ["capture"] and t["bronze"]["run_if"] == "ALL_DONE"
    assert [d["task_key"] for d in t["silver"]["depends_on"]] == ["bronze"]
    assert t["silver"]["run_if"] == "ALL_DONE"


def test_the_capture_task_is_never_retried_and_only_uploads_to_b2_through_the_bundle_variable():
    t = tasks()
    assert t["capture"]["disable_auto_optimization"] is True
    params = t["capture"]["notebook_task"]["base_parameters"]
    assert params["upload_to_b2"] == "${var.capture_b2}" and params["ping_healthchecks"] == "${var.ping}"
    assert t["capture"]["notebook_task"]["notebook_path"].endswith("p1_intake/notebooks/capture_task.py")


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
    assert all("disable_auto_optimization" not in t[k] for k in ("bronze", "silver", "taxonomy"))   # the capture is the other task with no retry


def test_no_task_gets_a_secret_as_a_parameter():
    for task in JOB["tasks"]:
        for name in task["notebook_task"]["base_parameters"]:
            assert not any(w in name.lower() for w in ("token", "password", "key", "hmac")), (task["task_key"], name)


def test_one_run_at_a_time_and_the_job_starts_at_0645_utc_with_room_for_the_poll():
    assert JOB["max_concurrent_runs"] == 1
    assert JOB["schedule"]["quartz_cron_expression"] == "0 45 6 * * ?" and JOB["schedule"]["pause_status"] == "UNPAUSED"
    assert JOB["timeout_seconds"] >= 7200   # the capture may poll OFF for an hour before the load starts


def test_the_notebooks_exist_in_the_repo():
    for task in JOB["tasks"]:
        path = (RESOURCES / task["notebook_task"]["notebook_path"]).resolve()
        assert path.exists(), path
