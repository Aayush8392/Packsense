import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
import run_job  # noqa: E402


def job(i, name):
    return NS(job_id=i, settings=NS(name=name))


JOBS = [job(1, "packsense-bronze-load"), job(2, "[dev packsense_deployer_dev] packsense-bronze-load"), job(3, "packsense-gold-build"),
        job(4, "[dev packsense_gold_dev] packsense-gold-build"), job(5, None)]


def test_a_unique_match_is_found_case_insensitively():
    assert run_job.pick_job(JOBS, "[DEV packsense_gold_dev]").job_id == 4


def test_exact_picks_the_production_job_whose_name_the_dev_copy_contains():
    assert run_job.pick_job(JOBS, "packsense-bronze-load", exact=True).job_id == 1
    assert run_job.pick_job(JOBS, "PACKSENSE-GOLD-BUILD", exact=True).job_id == 3
    assert run_job.pick_job(JOBS, "[dev packsense_gold_dev] packsense-gold-build", exact=True).job_id == 4
    with pytest.raises(LookupError, match="found 0"):
        run_job.pick_job(JOBS, "gold-build", exact=True)               # a part of a name is not enough


def test_zero_or_several_matches_are_refused():
    with pytest.raises(LookupError, match="found 2"):
        run_job.pick_job(JOBS, "packsense-bronze-load")
    with pytest.raises(LookupError, match="found 0"):
        run_job.pick_job(JOBS, "no-such-job")
