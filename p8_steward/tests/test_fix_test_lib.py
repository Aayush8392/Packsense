import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fix_test_lib as t  # noqa: E402

F100 = "en:nutrition-packaging-as-sold-100g-sugars-plus-starch-greater-than-carbohydrates"
FS = "en:nutrition-packaging-as-sold-serving-sugars-plus-starch-greater-than-carbohydrates"
# before: sugars 30 > carbohydrates 20 (breaks a rule); the fix set sugars 3.0
ROW = {"code": "1", "flags": F100, "serving_size": "50 g", "a_carbohydrates": 20.0, "a_sugars": 30.0, "b_carbohydrates": 20.0, "b_sugars": 3.0}


def test_group_and_serving_only_filter():
    assert t.group_of_row(ROW) == "D_sums_too_large"
    assert t.eligible(ROW) and not t.eligible({**ROW, "flags": FS}) and t.eligible({**ROW, "flags": F100 + "|" + FS})


def test_classes():
    assert t.classify(ROW, {"carbohydrates": 20.0, "sugars": 3.0}) == "agrees"
    assert t.classify(ROW, {"carbohydrates": 20.0, "sugars": 10.0}) == "valid_alternative"      # clears the rules, not the key
    assert t.classify(ROW, {"carbohydrates": 20.0, "sugars": 30.0}) == "breaks_rule"
    assert t.classify(ROW, None) == "abstain"


def test_code_baseline_returns_a_repair_that_clears_the_rules_or_none():
    p = t.code_proposal(ROW)
    assert p is None or not t.fc.violations({**t.before(ROW), **p})


def test_split_and_bracket():
    s = t.split(["agrees", "agrees", "valid_alternative", "breaks_rule", "abstain"])
    assert s["proposals"] == 4 and s["coverage"] == 0.8
    assert s["precision_agrees_only"][0] == 0.5 and s["precision_agrees_plus_alternatives"][0] == 0.75


def test_paired_counts_alternatives_as_not_agreeing_for_both():
    r = t.paired(["agrees", "valid_alternative", "agrees", "agrees"], ["valid_alternative", "valid_alternative", "agrees", "breaks_rule"])
    assert (r["wins"], r["losses"]) == (2, 0) and r["difference"] == 0.5
    assert t.paired(["agrees"], ["agrees"])["sign_test_p"] == 1.0


def test_printed_side():
    scan = {"responses": [{"fullTextAnnotation": {"pages": [{"blocks": [{"paragraphs": [{"words": [
        {"boundingBox": {"vertices": [{"x": 0, "y": 0}, {"x": 8, "y": 0}, {"x": 8, "y": 5}, {"x": 0, "y": 5}]}, "symbols": [{"text": "7,5"}]}]}]}]}]}}]}
    text = t.hk.scan_text(scan)
    assert t.printed_side(ROW, {"carbohydrates": 20.0, "sugars": 7.5}, text) == "agent_only"
    assert t.printed_side(ROW, {"carbohydrates": 20.0, "sugars": 3.0}, text) == "no_difference"


def test_agent_proposal_only_for_change_or_fill_in():
    assert t.agent_proposal({"action": "change to reading", "per100": {"sugars": 3.0}}) == {"sugars": 3.0}
    assert t.agent_proposal({"action": "no change", "per100": {}}) is None
    assert t.agent_proposal({"action": "abstain (the reading breaks a rule)", "per100": {"sugars": 3.0}}) is None


def test_agreement_is_judged_on_the_repaired_record_not_only_the_changed_field():
    row = {**ROW, "a_carbohydrates": 90.0, "b_carbohydrates": 20.0}        # the fix also corrected carbohydrates
    assert t.classify(row, {"sugars": 3.0}) != "agrees"                      # sugars alone leaves carbohydrates at 90
    assert t.classify(row, {"sugars": 3.0, "carbohydrates": 20.0}) == "agrees"


def test_clean_key_needs_the_post_fix_record_to_pass_every_rule():
    assert t.clean_key(ROW)                                                   # sugars 3.0 <= carbohydrates 20.0
    assert not t.clean_key({**ROW, "b_sugars": 30.0})                        # the fix left sugars above carbohydrates


def test_partner_fill_derives_only_the_stale_unprinted_partner():
    before = {"salt": 577.5, "sodium": 231.0, "energy_kcal": 477.0, "energy_kj": 296.5}
    out = t.complete_partners(before, {"sodium": 0.23, "energy_kcal": 477.0}, {"sodium": 0.23})
    assert out["sodium"] == 0.23 and out["salt"] == 0.575 and out["energy_kj"] == 1995.768
    assert t.complete_partners(before, {"sodium": 0.23, "salt": 0.58}, {"sodium": 0.23, "salt": 0.58}) == {"sodium": 0.23, "salt": 0.58}      # printed on the pack: left alone
    assert t.complete_partners({"salt": 0.58}, {"sodium": 0.23}, {"sodium": 0.23}) == {"sodium": 0.23}                                        # already consistent: no change
    assert t.complete_partners({"sodium": 5.0}, {"sodium": 0.23}, {"sodium": 0.23}) == {"sodium": 0.23}                                       # no stored salt: nothing to repair
    assert t.complete_partners(before, {"sodium": 0.23}, {"sodium": 0.23, "salt": 9.0})["salt"] == 9.0                                          # never overrides the proposal


def test_hybrid_pick_uses_the_reading_to_choose_among_code_candidates():
    # salt 577.5 and sodium 231 typed in milligrams as grams; the code can scale the flagged fields, the reading says the pack prints sodium 0.23
    row = {"code": "2", "flags": "en:nutrition-value-over-105-salt", "serving_size": "", "a_salt": 577.5, "a_sodium": 231.0, "b_salt": 0.58, "b_sodium": 0.23}
    pick = t.hybrid_pick(row, {"sodium": 0.23})
    assert pick is not None and abs(pick["sodium"] - 0.231) < 0.01
    assert t.hybrid_pick(row, None) == t.code_proposal(row)                      # no reading: the code's own first candidate
    assert t.hybrid_pick(ROW, {"sugars": 3.0}) is None                           # the code has no candidate for this one: the hybrid cannot invent one


def test_hybrid_agent_first_falls_back_to_code_when_the_agent_leaves_a_rule_broken():
    assert t.hybrid_agent_first(ROW, {"sugars": 3.0}) == {"sugars": 3.0}
    assert t.hybrid_agent_first(ROW, {"sugars": 30.0}) == t.code_proposal(ROW)  # still violates
    assert t.hybrid_agent_first(ROW, None) == t.code_proposal(ROW)


def test_hybrid_c_agent_first_then_the_reading_picks_a_code_candidate():
    row = {"code": "2", "flags": "en:nutrition-value-over-105-salt", "serving_size": "", "a_salt": 577.5, "a_sodium": 231.0, "b_salt": 0.58, "b_sodium": 0.23}
    assert t.hybrid_agent_then_reading(row, {"sodium": 0.23, "salt": 0.575}, {"sodium": 0.23}) == {"sodium": 0.23, "salt": 0.575}
    assert abs(t.hybrid_agent_then_reading(row, {"sodium": 0.23}, {"sodium": 0.23})["sodium"] - 0.231) < 0.01     # the agent's proposal leaves salt at 577.5: the reading picks a code candidate
    assert t.hybrid_agent_then_reading(row, None, None) == t.code_proposal(row)
