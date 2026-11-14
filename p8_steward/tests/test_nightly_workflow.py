"""The nightly workflow's schedule and its hand-over to the site build (switched on 2026-11-14 after the stage 2 pass). These pin the decisions so a later edit cannot undo one quietly:
the slot is after the Databricks export (08:50 UTC), only the job holds the extra permission, and the site build is started only after a successful real night."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8"))
ON = WF.get("on") or WF.get(True)          # YAML reads a bare `on` as the boolean True
JOB = WF["jobs"]["nightly"]
STEPS = {s.get("name") or s.get("uses") or s.get("run", ""): s for s in JOB["steps"]}
HAND_OVER = next(s for n, s in STEPS.items() if n.startswith("Start the site build"))


def test_the_schedule_is_on_after_the_export_and_after_the_quota_reset():
    crons = [s["cron"] for s in ON["schedule"]]
    assert crons == ["30 9 * * *"]
    minute, hour = (int(x) for x in crons[0].split()[:2])
    assert (hour, minute) > (8, 50)                         # the Databricks export runs at 08:50 UTC


def test_only_the_job_may_start_workflows_and_the_workflow_default_stays_read_only():
    assert WF["permissions"] == {"contents": "read"}
    assert JOB["permissions"] == {"contents": "read", "actions": "write"}


def test_the_site_build_is_started_only_after_a_successful_real_night_and_never_fails_the_night():
    assert HAND_OVER["if"] == "success()"
    assert HAND_OVER["continue-on-error"] is True
    run = HAND_OVER["run"]
    assert 'gh workflow run pages.yml --ref main' in run and '"$MODE" = "real"' in run
    assert HAND_OVER["env"]["GH_TOKEN"] == "${{ github.token }}"       # the workflow's own token, no stored secret
    assert list(JOB["steps"]).index(HAND_OVER) == len(JOB["steps"]) - 1  # after the healthchecks pings, so a hand-over problem cannot turn the failure ping on


def test_a_scheduled_run_is_a_real_night_at_the_agreed_cap():
    text = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    assert "MODE: ${{ inputs.mode || 'real' }}" in text and "MAX_CALLS: ${{ inputs.max_calls || '400' }}" in text
    assert WF["concurrency"] == {"group": "nightly", "cancel-in-progress": False}
