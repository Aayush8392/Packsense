"""Tests for the structured line and its validator (nightly/line_record.py)."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import line_record as lr  # noqa: E402

STORED = {"energy_kcal": 90.0, "energy_kj": 376.0, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
BOUND = {"rule": "saturated-fat-greater-than-fat", "stale_field": "saturated_fat", "stored": 5.0, "confirmed_field": "fat", "confirmed": 0.5, "kind": "at most"}


def line(**kw):
    base = dict(code="8901234567890", night="2026-11-13", table=dict(STORED), derived={}, differs=False, statement="checked", bounds=[], reading_basis="per 100 g", stored=STORED)
    base.update(kw)
    return lr.build_line(**base)


def test_a_built_line_is_valid_and_has_exactly_the_agreed_columns():
    ln = line()
    assert lr.validate_line(ln) == [] and sorted(ln) == sorted(lr.COLUMNS) and ln["line_type"] == "match" and ln["basis"] == "per_100"


def test_the_record_hash_follows_the_stored_values_only():
    h = lr.record_hash(STORED)
    assert h == lr.record_hash({**STORED, "fat": 0.5000001}) and h != lr.record_hash({**STORED, "fat": 0.6})
    assert h == lr.record_hash({**STORED, "fiber": None, "colour": "red"})          # None and unknown keys leave it unchanged
    assert line()["record_hash"] == h


def test_basis_is_per_100_only_for_a_per_100_reading():
    assert lr.basis_of("per 100 ml") == "per_100" and lr.basis_of("per serving (30 g)") == "per_serving_converted" and lr.basis_of(None) == "per_serving_converted"


def test_a_bound_statement_needs_a_bound_and_only_it_may_carry_one():
    assert lr.validate_line(line(statement="bound", bounds=[BOUND])) == []
    assert "a bound statement needs a bound" in lr.validate_line(line(statement="bound"))
    assert "bounds only belong to a bound statement" in lr.validate_line(line(statement="open", bounds=[BOUND]))


def test_free_text_and_odd_values_are_refused():
    ok = line()
    for mutate, expect in (
        (lambda d: d.update(statement="The pack looks fine"), "statement not allowed"),
        (lambda d: d.update(code="12"), "code is not 8 to 14 digits"),
        (lambda d: d.update(night="yesterday"), "night is not a date"),
        (lambda d: d["values"].update(fat="lots"), "values: value of fat out of range"),
        (lambda d: d["values"].update(fat=-1), "values: value of fat out of range"),
        (lambda d: d["values"].update(colour=1), "values: unknown field"),
        (lambda d: d.update(record_hash="abc"), "record_hash is not a sha256"),
        (lambda d: d.update(extra="x"), "columns differ from the line columns"),
    ):
        d = copy.deepcopy(ok)
        mutate(d)
        assert expect in lr.validate_line(d)


def test_a_line_with_fewer_than_three_values_is_refused():
    assert "values: fewer than 3 fields" in lr.validate_line(line(table={"fat": 0.5, "salt": 0.06}))


def test_a_bound_with_a_text_field_or_a_foreign_rule_is_refused():
    bad = {**BOUND, "rule": "something-else"}
    assert "bounds: value not allowed" in lr.validate_line(line(statement="bound", bounds=[bad]))
    ln = line(statement="bound", bounds=[BOUND])
    ln["bounds"][0]["text"] = "free sentence"
    assert "bounds: wrong keys" in lr.validate_line(ln)
