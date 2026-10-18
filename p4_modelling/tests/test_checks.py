"""The closing volume and freshness checks (2026-10-18): the model list stays complete and the wall-clock check stays out of the fixture runs."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gold_lib import compare  # noqa: E402

TESTS = ROOT / "data_tests"


def test_every_compared_model_is_in_the_volume_floor_check():
    text = (TESTS / "every_model_has_rows.sql").read_text(encoding="utf-8")
    listed = set(re.findall(r"'([a-z_]+)'", text.split("{% set models = [")[1].split("] %}")[0]))
    assert listed == set(compare.MODELS), (listed ^ set(compare.MODELS))


def test_the_freshness_check_is_a_warning_and_never_runs_on_the_fixture():
    text = (TESTS / "silver_is_fresh.sql").read_text(encoding="utf-8")
    config = text.split("}}", 1)[0]
    assert "severity='warn'" in config
    assert "target.type == 'databricks'" in config and "fixture_mode" in config
    assert "current_timestamp" in text


def test_the_other_new_checks_do_not_read_the_clock():
    for name in ("every_model_has_rows", "quality_fact_has_every_group_every_day", "history_not_below_status"):
        text = (TESTS / f"{name}.sql").read_text(encoding="utf-8")
        assert "current_timestamp" not in text and "current_date" not in text, name


def test_the_status_check_is_a_warning():
    assert "severity='warn'" in (TESTS / "history_not_below_status.sql").read_text(encoding="utf-8").split("}}", 1)[0]
