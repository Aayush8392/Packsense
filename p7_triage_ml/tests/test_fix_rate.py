"""The Kaplan-Meier part of the fix-rate analysis, on the real counts of the error-flag spells (13,034 spells of the flag-event table, 2026-11-03), checked against a second,
independent way of counting (a direct product over the event times) and against the numbers that can be read off the counts by hand."""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "analysis"))
sys.path.insert(0, str(HERE.parents[1] / "p9_operations"))
import fix_rate as fr  # noqa: E402

SPELLS = [tuple(x) for x in json.loads((HERE / "fixtures" / "fix_rate_error_spells.json").read_text(encoding="utf-8"))["spells"]]


def _direct(spells, horizon):
    """Product-limit estimate written the long way: for every time t <= horizon, fixed(t) / (spells whose duration is at least t)."""
    survival = 1.0
    for t in sorted({t for t, e, _ in spells if e and t <= horizon}):
        at_risk = sum(n for d, _, n in spells if d >= t)
        fixed = sum(n for d, e, n in spells if d == t and e)
        survival *= 1 - fixed / at_risk
    return survival


def test_the_counts_are_the_whole_error_flag_population():
    assert sum(n for _, _, n in SPELLS) == 13034 and all(t >= 0 and e in (0, 1) and n > 0 for t, e, n in SPELLS)


def test_the_first_step_can_be_read_off_the_counts_by_hand():
    curve = fr.kaplan_meier(SPELLS)
    t, at_risk, fixed, s = curve[0]
    assert (t, at_risk, fixed) == (1, 11554, 101) and s == 1 - 101 / 11554              # 101 of the 11,554 spells still open after one step were fixed in step 1


def test_the_estimate_equals_the_direct_product_at_every_horizon_and_never_rises():
    curve = fr.kaplan_meier(SPELLS)
    for h in (1, 2, 4, 8, 12):
        assert math.isclose(1 - fr.fixed_by(curve, h), _direct(SPELLS, h), rel_tol=1e-12)
    surv = [s for *_, s in curve]
    assert surv == sorted(surv, reverse=True) and 0 < surv[-1] < 1
    assert fr.fixed_by(curve, 0) == 0.0 and fr.fixed_by(curve, 1) < fr.fixed_by(curve, 2) < fr.fixed_by(curve, 4) < fr.fixed_by(curve, 8)


def test_a_group_that_never_reaches_half_has_no_median_and_censoring_keeps_people_at_risk():
    curve = fr.kaplan_meier(SPELLS)
    assert fr.median_steps(curve) is None
    assert fr.median_steps([(1, 5, 4, 0.2)]) == 1
    assert fr.kaplan_meier([(1, 0, 10), (2, 1, 1)])[0][1] == 1                          # the ten censored at step 1 are no longer at risk at step 2


def test_the_family_name_drops_the_nutrition_prefix_and_the_language_of_the_tag():
    assert fr.family_of("en:nutrition-salt-does-not-match-sodium") == "salt-does-not-match-sodium"
    assert fr.family_of("en:nutrition-packaging-as-sold-100g-salt-does-not-match-sodium") == "salt-does-not-match-sodium"
    assert fr.family_of("en:no-nutrition-data") == "no-nutrition-data"
