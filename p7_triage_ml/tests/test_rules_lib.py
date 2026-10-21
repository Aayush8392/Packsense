"""p7_triage_ml/rules_lib.py: the boundaries of every tolerance, missing inputs, and the flag-family mapping."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rules_lib as r  # noqa: E402

# a real-looking product: 100 g of chocolate-ish food, energy consistent with its nutrients
GOOD = {"energy-kj": 2200, "energy-kcal": 525, "fat": 30, "saturated-fat": 18, "carbohydrates": 55, "sugars": 50, "proteins": 6, "salt": 0.2, "sodium": 0.08, "fiber": 3}


def v(**over):
    n = dict(GOOD)
    n.update(over)
    return n


def test_a_consistent_product_violates_nothing():
    got = r.verdicts(GOOD)
    assert [k for k, x in got.items() if x.status == "violated"] == []
    assert got["value-over-105"].status == "ok" and got["salt-does-not-match-sodium"].status == "ok"


def test_every_rule_returns_not_applicable_on_an_empty_product():
    assert all(x.status == "not_applicable" for x in r.verdicts({}).values())


@pytest.mark.parametrize("kj,kcal,rule,expected", [
    (2000, 500, "energy-value-in-kcal-greater-than-in-kj", "ok"),
    (400, 2000, "energy-value-in-kcal-greater-than-in-kj", "violated"),
    (400, 1680, "energy-value-in-kcal-and-kj-are-reversed", "violated"),              # kcal 1680 is about 4.2 x 400: the two columns swapped
    (2000, 500, "energy-value-in-kcal-and-kj-are-reversed", "ok"),
    (1850, 500, "energy-value-in-kcal-does-not-match-value-in-kj", "ok"),             # 3.7*500-2 = 1848 <= 1850
    (1847, 500, "energy-value-in-kcal-does-not-match-value-in-kj", "violated"),       # just under the low bound
    (2352, 500, "energy-value-in-kcal-does-not-match-value-in-kj", "ok"),             # 4.7*500+2 = 2352
    (2353, 500, "energy-value-in-kcal-does-not-match-value-in-kj", "violated"),
])
def test_kj_and_kcal_rules_at_their_boundaries(kj, kcal, rule, expected):
    assert r.RULES[rule]({"energy-kj": kj, "energy-kcal": kcal}).status == expected


def test_energy_over_3911_is_strict():
    assert r.energy_over_3911({"energy-kj": 3911}).status == "ok"
    assert r.energy_over_3911({"energy-kj": 3912}) == r.violated(1)


def test_computed_energy_follows_ofs_factors_and_polyols():
    n = {"carbohydrates": 50, "fat": 10, "proteins": 5, "fiber": 2}
    assert r.computed_energy(n, "kj") == 50 * 17 + 10 * 37 + 5 * 17 + 2 * 8
    assert r.computed_energy(n, "kcal") == 50 * 4 + 10 * 9 + 5 * 4 + 2 * 2
    p = {"carbohydrates": 50, "fat": 0, "proteins": 0, "polyols": 10, "erythritol": 4}              # (50-10)*17 + (10-4)*10 + 4*0
    assert r.computed_energy(p, "kj") == 40 * 17 + 6 * 10
    s = {"carbohydrates": 50, "fat": 0, "proteins": 0, "maltitol": 6, "erythritol": 4}              # polyols summed from their parts: 10
    assert r.computed_energy(s, "kj") == r.computed_energy(p, "kj")
    assert r.computed_energy({"carbohydrates": 50, "fat": 1}, "kj") is None                           # proteins missing: OFF computes nothing


def test_energy_against_computed_has_error_warning_and_ok_bands():
    base = {"carbohydrates": 50, "fat": 10, "proteins": 5, "fiber": 0}                                 # computed 1305 kJ
    comp = r.computed_energy(base, "kj")
    rule = r.energy_kj_does_not_match_computed
    assert rule({**base, "energy-kj": comp}).status == "ok"
    assert rule({**base, "energy-kj": comp / 1.2}).severity == "warning"                              # computed ~20% above the specified value
    assert rule({**base, "energy-kj": comp / 1.5}).severity == "error"
    assert rule({**base, "energy-kj": comp * 1.5}).severity == "error"
    assert rule({"energy-kj": 30, "carbohydrates": 1, "fat": 0, "proteins": 0}).status == "not_applicable"      # both under 55 kJ: OFF does not check
    assert rule({"energy-kj": 1305}).status == "not_applicable"                                       # cannot compute


def test_salt_against_sodium_tolerance():
    assert r.salt_does_not_match_sodium({"salt": 1.0, "sodium": 0.4}).status == "ok"
    assert r.salt_does_not_match_sodium({"salt": 1.1, "sodium": 0.4}).status == "ok"                  # a gap of exactly 0.1 is allowed
    assert r.salt_does_not_match_sodium({"salt": 1.2, "sodium": 0.4}).status == "violated"
    assert r.salt_does_not_match_sodium({"salt": 1.2}).status == "not_applicable"


@pytest.mark.parametrize("carbs,sugars,starch,expected", [
    (5, 5, None, "ok"),
    (5, 5.01, None, "ok"),                 # under 10 g the slack is 0.01
    (5, 5.02, None, "violated"),
    (20, 20.1, None, "ok"),                # from 10 g up it is 0.1
    (20, 20.2, None, "violated"),
    (20, 12, 8.3, "violated"),             # sugars + starch together
    (0, 0.4, None, "ok"),                  # a stated 0 counts as the trace 0.5 g
    (0, 0.6, None, "violated"),
])
def test_sugars_plus_starch_against_carbohydrates(carbs, sugars, starch, expected):
    n = {"carbohydrates": carbs, "sugars": sugars}
    if starch is not None:
        n["starch"] = starch
    assert r.sugars_plus_starch_greater_than_carbohydrates(n).status == expected


def test_saturated_fat_against_fat():
    assert r.saturated_fat_greater_than_fat({"fat": 10, "saturated-fat": 10.2}).status == "violated"
    assert r.saturated_fat_greater_than_fat({"fat": 10, "saturated-fat": 10.1}).status == "ok"
    assert r.saturated_fat_greater_than_fat({"fat": 10}).status == "not_applicable"


def test_impossible_quantities():
    assert r.value_over_105({"fat": 105}).status == "ok" and r.value_over_105({"fat": 105.5}) == r.violated(0.5)
    assert r.value_over_105({"energy-kj": 4000}).status == "not_applicable"                          # energy is not a mass
    assert r.value_total_over_105({"fat": 30, "carbohydrates": 40, "proteins": 30, "salt": 5.1}).status == "violated"
    assert r.value_total_over_105({"fat": 30, "carbohydrates": 40, "proteins": 30, "salt": 5}).status == "ok"
    assert r.value_total_over_105({"sugars": 3}).status == "not_applicable"


def test_flag_families_map_to_their_rule():
    assert r.rule_for_family("salt-does-not-match-sodium") == "salt-does-not-match-sodium"
    assert r.rule_for_family("value-over-105-sugars") == "value-over-105"
    assert r.rule_for_family("energy-value-in-kcal-may-not-match-value-computed-from-other-nutrients") == "energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients"
    assert r.rule_for_family("value-under-0-01-g-salt") is None
    assert all(r.rule_for_family(name) == name for name in r.RULES)
