"""Tests for the final-block rule check (final_rulecheck.py): pure logic with a fake rule set."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import final_rulecheck as rc  # noqa: E402


def viol(rec):
    return ["fat above 100"] if rec.get("fat", 0) > 100 else (["kcal and kJ disagree"] if rec.get("bad") else [])


def run(stored, table, key="sample", answer="right"):
    rows = {"1": {"stored": stored}}
    dec = {"1": {"rule2": True, "table": table}}
    return rc.check(rows, dec, {"1": key}, {"1": answer}, viol=viol, before=lambda r: r["stored"], repair=lambda b, tab: ({**b, **tab}, {}), bounds=lambda *a: [])


def test_a_repair_that_removes_the_violation_clears_the_flag():
    r = run({"fat": 500}, {"fat": 5.0})
    assert r["stored_record_breaks_a_rule"] == 1 and r["flag_cleared"] == 1 and r["repaired_breaks_a_rule"] == 0
    assert r["matches_the_pack_but_fails_the_rules"] == []


def test_a_pack_that_prints_an_impossible_value_is_listed_as_matching_the_pack_but_failing_the_rules():
    r = run({"fat": 5}, {"fat": 150})
    assert r["flag_not_cleared"] == 0 and r["stored_clean_repaired_breaks"] == 1
    assert [f["code"] for f in r["matches_the_pack_but_fails_the_rules"]] == ["1"]


def test_a_decoy_line_never_counts_as_matching_the_pack():
    r = run({"fat": 5}, {"fat": 150}, key="decoy", answer="wrong")
    assert r["matches_the_pack_but_fails_the_rules"] == [] and len(r["fail_the_rules_other"]) == 1
