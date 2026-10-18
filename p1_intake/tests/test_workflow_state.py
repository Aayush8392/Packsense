"""Workflow-state check: which workflows are reported.

The paths and the `active` state are the real ones from GitHub's Actions API for this repository on 2026-10-18 (13 workflows, all
active); the other states are the values the API documents (`disabled_inactivity`, `disabled_manually`, `disabled_fork`, `deleted`).
The end-to-end proof is the workflow's own manual run: with the default it must go green on the real list, and with `expect_state`
set to something else it must go red.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_workflow_state import not_in_state  # noqa: E402

REAL = [
    {"path": ".github/workflows/capture.yml", "name": "Capture", "state": "active"},
    {"path": ".github/workflows/keepalive.yml", "name": "Keep-alive", "state": "active"},
    {"path": "dynamic/github-code-scanning/codeql", "name": "CodeQL", "state": "active"},
]


def test_all_active_reports_nothing():
    assert not_in_state(REAL) == []


def test_a_workflow_disabled_by_inactivity_is_reported():
    ws = REAL[:1] + [dict(REAL[1], state="disabled_inactivity")] + REAL[2:]
    assert not_in_state(ws) == [(".github/workflows/keepalive.yml", "Keep-alive", "disabled_inactivity")]


def test_every_documented_non_active_state_is_reported_in_path_order():
    ws = [dict(REAL[2], state="deleted"), dict(REAL[1], state="disabled_manually"), dict(REAL[0], state="disabled_fork")]
    assert [r[0] for r in not_in_state(ws)] == sorted(w["path"] for w in ws)
    assert {r[2] for r in not_in_state(ws)} == {"deleted", "disabled_manually", "disabled_fork"}


def test_an_expectation_other_than_active_reports_the_active_ones():
    assert len(not_in_state(REAL, "disabled_manually")) == len(REAL)
