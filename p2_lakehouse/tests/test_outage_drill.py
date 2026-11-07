"""The pure decisions inside the outage drill: which days, the pass rule, and the cost estimate."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import outage_drill as o  # noqa: E402

DAY = 86_400


def name(start, end):
    return f"openfoodfacts_products_{start}_{end}.json.gz"


# five consecutive days, as the capture names them (start and end are Unix seconds)
FILES = [name(1_790_000_000 + i * DAY, 1_790_000_000 + (i + 1) * DAY) for i in range(5)]


def test_end_time_is_read_from_the_file_name():
    assert o.end_time(FILES[0]) == 1_790_000_000 + DAY
    assert o.end_time("manifests") is None
    assert o.end_time("openfoodfacts_products_delta_20261001.json.gz") is None


def test_pick_takes_the_latest_n_loaded_days_in_order():
    got = o.pick_latest_loaded(FILES, set(FILES), set(FILES), 3)
    assert got == FILES[2:]


def test_pick_skips_a_day_production_has_not_finished_in_both_layers():
    done_b, done_s = set(FILES), set(FILES) - {FILES[4]}          # the newest day is not in silver yet
    assert o.pick_latest_loaded(FILES, done_b, done_s, 3) == FILES[1:4]


def test_pick_ignores_files_that_are_not_deltas():
    assert o.pick_latest_loaded(FILES + ["manifests", "readme.txt"], set(FILES), set(FILES), 2) == FILES[3:]


def test_pick_refuses_when_there_are_too_few_days():
    with pytest.raises(ValueError, match="need 6"):
        o.pick_latest_loaded(FILES, set(FILES), set(FILES), 6)


def test_span_days_counts_from_the_first_start_to_the_last_end():
    assert o.span_days(FILES[2:]) == pytest.approx(3.0)


def test_gaps_are_found_when_a_day_is_missing():
    chosen = [FILES[0], FILES[2], FILES[3]]                       # day 2 never landed
    assert o.gaps(chosen) == [(FILES[0], FILES[2])]
    assert o.gaps(FILES) == []


def test_second_pass_must_add_nothing():
    before = {"bronze_rows": 100, "silver_rows": 98, "silver_quarantine": 2, "bronze_manifest": 3, "silver_manifest": 3}
    assert o.second_pass_problems(before, dict(before)) == []
    after = dict(before, silver_rows=99)
    assert o.second_pass_problems(before, after) == ["silver_rows changed on the second pass: 98 -> 99"]


def test_verdict_is_pass_only_when_every_part_is_clean():
    assert o.verdict([], [], []) == "PASS"
    assert o.verdict(["bronze row count 5 differs from production 6"], [], []).startswith("FAIL")
    assert o.verdict([], [], ["x changed"]).startswith("FAIL")


def test_estimate_scales_the_measured_cost_by_rows():
    # 3 days of 18,000 rows took 600 job-seconds; 20 days of 120,000 rows is 6.67 times the rows
    assert o.estimate_seconds(600, 18_000, 120_000) == pytest.approx(4000)
    with pytest.raises(ValueError):
        o.estimate_seconds(600, 0, 120_000)
