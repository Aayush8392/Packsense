import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import report_sealed_test as rs  # noqa: E402


def row(action, stored_right=True, proposal_right=None, height=25.0):
    return {"code": "x", "action": action, "stored_right": stored_right, "proposal_right": proposal_right, "height": height}


def test_wilson_known_values():
    lo, hi = rs.wilson(46, 50)
    assert round(lo, 3) == 0.812 and round(hi, 3) == 0.968      # 46 of 50 passes the bar (lower bound at least 0.80)
    lo45, _ = rs.wilson(45, 50)
    assert lo45 < 0.80          # 45 of 50 does not pass
    assert rs.wilson(0, 0) == (0.0, 0.0)


def test_a2026_examples_of_the_bar():
    def run(right, n):
        return rs.summarise([row("change to reading", False, i < right) for i in range(n)])["bar"]
    assert run(46, 50) == "PASS"
    assert run(45, 50) == "FAIL"             # 90% point, lower bound under 80%
    assert run(37, 40) == "PASS"
    assert run(36, 40) == "FAIL"
    assert run(30, 30).startswith("INCONCLUSIVE")


def test_band_edges():
    assert rs.band_of(14.9) == "under 15 px" and rs.band_of(15) == "15 to 20 px" and rs.band_of(49.9) == "30 to 50 px" and rs.band_of(50) == "50 px and up"
    assert rs.band_of(None) == "no word height"


def test_planted_violations_are_counted():
    rows = [row("change to reading", False, True)] * 3 + [row("change to reading", False, False)] + [row("no change", True)] * 2 + [row("no change", False)] + [row("abstain (x)")] * 4
    s = rs.summarise(rows)
    assert (s["proposals"]["k"], s["proposals"]["n"]) == (3, 4)
    assert (s["match_verdicts"]["k"], s["match_verdicts"]["n"]) == (2, 3)
    assert s["silent_misses"]["k"] == 1 and s["abstentions"]["k"] == 4 and s["coverage"]["k"] == 7 and s["cards"] == 11


def test_band_switch_needs_15_and_lower_bound():
    few = rs.summarise([row("fill in", False, True, 40.0)] * 14)["bands"]["30 to 50 px"]
    assert few["switched_on"] is False
    enough = rs.summarise([row("fill in", False, True, 40.0)] * 20)["bands"]["30 to 50 px"]
    assert enough["switched_on"] is True
    weak = rs.summarise([row("fill in", False, i < 14, 40.0) for i in range(20)])["bands"]["30 to 50 px"]
    assert weak["switched_on"] is False


def test_families_of_reads_the_error_tags_in_priority_order():
    tags = ["en:nutrition-saturated-fat-greater-than-fat", "en:nutrition-energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients", "en:ingredients-fr-photo-to-be-selected"]
    assert rs.families_of(tags) == ["A_energy_mismatch", "D_sums_too_large"]
    assert rs.families_of(json.dumps(["en:nutrition-values-are-all-identical"])) == ["E_other_nutrition"]
    assert rs.families_of(None) == [] and rs.families_of([]) == []


def test_a_proposal_on_a_field_the_key_lacks_is_dropped_not_counted_wrong_but_a_silent_match_stays_wrong():
    rows = [row("change to reading", False, True)] * 4 + [row("change to reading", False, False)] + [dict(row("change to reading", False, False), unscorable=True)] * 3
    rows += [dict(row("no change", False), unscorable=True)]          # a 'no change' on a record with an unprinted value is the reader's fault: not dropped
    s = rs.summarise(rows)
    assert (s["proposals"]["k"], s["proposals"]["n"], s["dropped_unscorable"]) == (4, 5, 3)
    assert s["match_verdicts"]["n"] == 1 and s["silent_misses"]["k"] == 1


def fam(k, n):
    return {"proposals": rs.rate(k, n)}


def test_weighted_bar_stops_the_easy_family_from_dominating():
    # C is perfect and large; A is weak: the unweighted pool looks fine, the weighted reading must not
    fams = {"A_energy_mismatch": fam(5, 10), "C_values_too_large": fam(40, 40)}
    pooled = 45 / 50
    wb = rs.weighted_bar(fams, {"A_energy_mismatch": 438, "C_values_too_large": 442})
    assert pooled == 0.9 and wb["point"] < 0.80
    assert abs(sum(v["weight"] for v in wb["per_family"].values()) - 1) < 1e-3
    assert rs.weighted_verdict(wb, 50) == "FAIL"


def test_weighted_bar_passes_when_every_family_is_clean_and_renormalises_missing_ones():
    fams = {f: fam(n, n) for f, n in (("A_energy_mismatch", 30), ("C_values_too_large", 30), ("D_sums_too_large", 20))}
    wb = rs.weighted_bar(fams)
    assert abs(wb["point"] - 1.0) < 1e-9 and wb["lower95"] >= 0.80
    assert wb["weight_left_out"] > 0 and "B_salt_vs_sodium" not in wb["families_used"]        # B and E had no proposals: their weight is reported as left out
    assert rs.weighted_verdict(wb, 80) == "PASS"
    assert rs.weighted_verdict(wb, 39).startswith("INCONCLUSIVE")                              # fewer than 40 proposals is never a pass


def test_weighted_bar_one_field_variant_one_wrong_proposal_in_a_small_family_costs_its_weight():
    base = {"A_energy_mismatch": fam(20, 20), "B_salt_vs_sodium": fam(5, 5), "C_values_too_large": fam(20, 20)}
    worse = {**base, "B_salt_vs_sodium": fam(4, 5)}
    assert rs.weighted_bar(worse)["point"] < rs.weighted_bar(base)["point"]
    assert rs.weighted_bar({})["point"] is None
