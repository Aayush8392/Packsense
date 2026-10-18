"""Logic of the manual production gold build helper, checked against stand-ins for the Databricks client.

The job name is the real one; the stand-ins carry only what the helper reads. The end-to-end proof is the real run of
2026-10-18 (run 580735387546416: started by the admin, success, 165 nodes).
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import run_gold_prod as r  # noqa: E402

NAME = "packsense-gold-build"


def job(job_id, name=NAME):
    return NS(job_id=job_id, settings=NS(name=name))


def run(life, result=None):
    return NS(state=NS(life_cycle_state=NS(value=life), result_state=NS(value=result) if result else None))


class FakeJobs:
    def __init__(self, jobs=(), runs=(), active=()):
        self._jobs, self._runs, self._active = list(jobs), list(runs), list(active)
        self.polled = 0

    def list(self, name=None):
        return iter(self._jobs)

    def list_runs(self, job_id=None, active_only=False):
        return iter(self._active)

    def get_run(self, run_id):
        run_obj = self._runs[min(self.polled, len(self._runs) - 1)]
        self.polled += 1
        return run_obj


def test_exactly_one_job_is_found():
    assert r.find_job_id(NS(jobs=FakeJobs(jobs=[job(7)])), NAME) == 7


def test_a_missing_job_is_refused():
    with pytest.raises(LookupError):
        r.find_job_id(NS(jobs=FakeJobs(jobs=[])), NAME)


def test_two_jobs_with_the_name_are_refused():
    with pytest.raises(LookupError):
        r.find_job_id(NS(jobs=FakeJobs(jobs=[job(7), job(8)])), NAME)


def test_a_job_with_a_different_name_is_not_taken():
    with pytest.raises(LookupError):
        r.find_job_id(NS(jobs=FakeJobs(jobs=[job(7, "something-else")])), NAME)


def test_active_runs_are_listed():
    w = NS(jobs=FakeJobs(active=[NS(run_id=11), NS(run_id=12)]))
    assert r.active_run_ids(w, 7) == [11, 12]


def test_waiting_ends_when_the_run_terminates():
    jobs = FakeJobs(runs=[run("PENDING"), run("RUNNING"), run("TERMINATED", "SUCCESS")])
    now = {"t": 0.0}
    done = r.wait_for(NS(jobs=jobs), 1, 600, poll_s=15, sleep=lambda s: now.update(t=now["t"] + s), clock=lambda: now["t"])
    assert r.succeeded(done) and jobs.polled == 3


def test_waiting_gives_up_at_the_timeout_without_a_verdict():
    jobs = FakeJobs(runs=[run("RUNNING")])
    now = {"t": 0.0}
    done = r.wait_for(NS(jobs=jobs), 1, 60, poll_s=15, sleep=lambda s: now.update(t=now["t"] + s), clock=lambda: now["t"])
    assert done.state.life_cycle_state.value == "RUNNING" and not r.succeeded(done)


def test_a_failed_run_is_not_a_success():
    assert not r.succeeded(run("TERMINATED", "FAILED"))
    assert not r.succeeded(run("INTERNAL_ERROR"))
