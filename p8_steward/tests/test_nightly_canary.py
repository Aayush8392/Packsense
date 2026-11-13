"""Tests for the nightly canary comparison (nightly/canary.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import canary as cn  # noqa: E402

RIGHT = {"energy_kcal": 90, "energy_kj": 376, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
WRONG = {**RIGHT, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0}


def expected(n):
    return {f"c{i}": dict(RIGHT) for i in range(n)}


def test_all_agreeing_passes():
    r = cn.compare(expected(10), expected(10))
    assert r == {"total": 10, "agreed": 10, "missed": [], "passed": True, "reason": None}


def test_one_miss_is_within_the_tolerance_and_two_are_not():
    prod = expected(10)
    prod["c3"] = WRONG
    assert cn.compare(prod, expected(10))["passed"] is True
    prod["c4"] = WRONG
    r = cn.compare(prod, expected(10))
    assert r["passed"] is False and r["missed"] == ["c3", "c4"] and r["reason"] == "too_many_misses"


def test_a_silence_or_an_absent_product_counts_as_a_miss():
    prod = expected(10)
    prod["c0"] = None
    del prod["c1"]
    r = cn.compare(prod, expected(10))
    assert r["missed"] == ["c0", "c1"] and r["agreed"] == 8 and r["passed"] is False


def test_an_empty_canary_never_passes():
    assert cn.compare({}, {}) == {"total": 0, "agreed": 0, "missed": [], "passed": False, "reason": "no_canary"}


def test_the_tolerance_is_a_parameter():
    prod = expected(4)
    prod["c0"] = WRONG
    assert cn.compare(prod, expected(4), max_miss=0)["passed"] is False
