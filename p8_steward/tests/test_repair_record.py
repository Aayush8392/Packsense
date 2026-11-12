"""Tests for the repaired record and the bound statements (repair_record.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import repair_record as rr  # noqa: E402


def test_a_stale_sodium_is_replaced_by_the_value_derived_from_the_salt_the_line_gives():
    rec, derived = rr.repaired_record({"salt": 0.0012, "sodium": 0.00012, "fat": 1.0}, {"salt": 0.12})
    assert rec["sodium"] == 0.048 and derived == {"sodium": 0.048} and rec["salt"] == 0.12 and rec["fat"] == 1.0


def test_a_stored_partner_within_10_percent_is_left_alone_and_a_missing_one_is_added():
    rec, derived = rr.repaired_record({"sodium": 0.19}, {"salt": 0.48})
    assert rec["sodium"] == 0.19 and derived == {}
    rec, derived = rr.repaired_record({}, {"energy_kcal": 100.0})
    assert derived == {"energy_kj": 418.4}


def test_nothing_is_derived_when_the_line_gives_both_sides_or_neither():
    rec, derived = rr.repaired_record({"sodium": 0.5}, {"salt": 0.3, "sodium": 0.12})
    assert derived == {} and rec["sodium"] == 0.12
    assert rr.repaired_record({"sodium": 0.5}, {"fat": 1.0})[1] == {}


def test_a_stored_value_the_line_does_not_speak_to_is_never_deleted():
    rec, _ = rr.repaired_record({"fiber": 16.0, "saturated_fat": 3.6}, {"fat": 2.1})
    assert rec["fiber"] == 16.0 and rec["saturated_fat"] == 3.6


def test_a_bound_exists_only_for_a_hard_law_with_one_confirmed_and_one_stored_side():
    s = rr.bound_statements({"saturated_fat": 3.6, "fat": 6.5}, {"fat": 2.1}, {"saturated-fat-greater-than-fat"})
    assert len(s) == 1 and s[0]["stale_field"] == "saturated_fat" and s[0]["kind"] == "at most" and "must be at most 2.1 g" in s[0]["text"]
    s = rr.bound_statements({"saturated_fat": 1.0, "fat": 0.5}, {"saturated_fat": 2.0}, {"saturated-fat-greater-than-fat"})
    assert s[0]["stale_field"] == "fat" and s[0]["kind"] == "at least"
    assert rr.bound_statements({"saturated_fat": 3.6}, {"saturated_fat": 3.6, "fat": 2.1}, {"saturated-fat-greater-than-fat"}) == []      # both sides confirmed: no stale side
    assert rr.bound_statements({"saturated_fat": 3.6, "fat": 6.5}, {"fat": 2.1}, {"energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients"}) == []
