"""Tests for guard v2 (guard_v2.py): the two added rules and their limits."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import answer_key_lib as ak  # noqa: E402
import guard_v2 as g  # noqa: E402

TEXT = "Fett | 7,79\nKohlenhydrate 819\nEnergie 396 kJ 95 kcal\nSalz 1,0 g\nProtein 5,4 g"


def run(values, text=TEXT):
    g.LOG.clear()
    return g.grounded_values_v2(values, text)


def test_the_original_guard_is_untouched_and_exact_matches_need_nothing():
    kept, dropped = run({"salt": 1.0, "energy_kcal": 95.0})
    assert kept == {"salt": 1.0, "energy_kcal": 95.0} and dropped == [] and g.LOG == []
    assert ak.grounded_values is g._ORIGINAL


def test_first_decimal_rule_accepts_7_7_for_7_79_but_not_7_8():
    kept, dropped = run({"fat": 7.7})
    assert kept == {"fat": 7.7} and g.LOG[0]["rule"] == "first_decimal" and g.LOG[0]["token"] == "7.79"
    kept, dropped = run({"fat": 7.8})
    assert kept == {} and dropped == ["fat"]


def test_trailing_9_rule_accepts_81_for_819_the_photo_value_stays():
    kept, dropped = run({"carbohydrates": 81.0})
    assert kept == {"carbohydrates": 81.0} and g.LOG[0]["rule"] == "trailing_9" and g.LOG[0]["token"] == "819"


def test_a_two_digit_whole_number_never_matches_a_neighbour_such_as_5_for_59():
    kept, dropped = run({"proteins": 5.0}, "Protein 59 g\nFett 1,0 g")
    assert dropped == ["proteins"]


def test_energy_and_zero_are_never_recovered():
    kept, dropped = run({"energy_kcal": 39.0, "fat": 0.0}, "Energie 399 kJ\nFett 0,09 g")
    assert "energy_kcal" in dropped and g.LOG == []                     # v2 recovered nothing: not the energy, not the zero (whatever the original guard did with it)


def test_an_ambiguous_value_or_a_token_another_field_already_prints_is_not_recovered():
    kept, dropped = run({"fat": 7.7}, "Fett 7,79\nDavon 7,75")
    assert dropped == ["fat"]
    kept, dropped = run({"fat": 7.7, "sugars": 7.79}, "Fett 7,79")
    assert kept == {"sugars": 7.79} and dropped == ["fat"]


def test_installed_swaps_the_guard_only_inside_the_block():
    with g.installed():
        assert ak.grounded_values is g.grounded_values_v2
    assert ak.grounded_values is g._ORIGINAL
