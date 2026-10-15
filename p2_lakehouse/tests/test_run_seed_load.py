"""The seed run script refuses anything that looks like a secret value as a job parameter."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import run_seed_load as r  # noqa: E402


def test_ordinary_parameters_pass():
    r.check_params({"mode": "stage", "hf_secret_name": "hf_dump_read_token", "dump_date": "2026-10-13", "last_part": "0003",
                    "stage_schema": "workspace.packsense_seed_stage"})


@pytest.mark.parametrize("value", ["hf_" + "a" * 30, "K003" + "b" * 25, "dapi" + "c" * 30, "ghp_" + "d" * 36])
def test_token_shaped_values_are_refused(value):
    with pytest.raises(SystemExit):
        r.check_params({"hf_secret_name": value})
