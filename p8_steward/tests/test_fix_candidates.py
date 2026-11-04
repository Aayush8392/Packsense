"""Candidate fixes for nutrition flags (item 23): what the code finds on the six sample products, and the properties that must always hold.

The six products are real rows of the committed fixture. The expected repairs come from reading each product's nutrition photo (see the review sample of
2026-11-04), so these tests pin development behaviour; they are NOT a measurement of the method (the six were seen while it was being built).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import fix_candidates as fc  # noqa: E402

ROWS = [json.loads(line) for line in (ROOT / "p4_modelling" / "fixtures" / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def product(code: str):
    versions = sorted((r for r in ROWS if r["code"] == code), key=lambda r: r["last_modified_t"])
    return versions[-1], (versions[-2] if len(versions) > 1 else None)


def run(code: str) -> list[dict]:
    cur, prev = product(code)
    return fc.candidates(cur, prev, cur.get("serving_quantity"))


def finals(cands: list[dict], field: str) -> list[float]:
    return [c["values"].get(field) for c in cands]


def close(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol * max(abs(b), 1e-9)


SAMPLE = ["8901063341500", "8410320127363", "8901595852321", "8906002661404", "0677210091823", "7613036892520"]


def test_white_bread_milligrams_typed_as_grams_is_found_and_ranked_first():
    c = run("8901063341500")
    assert c[0]["kind"] == "scale_flagged" and close(c[0]["values"]["salt"], 1.1) and close(c[0]["values"]["sodium"], 0.44)
    assert set(c[0]["changes"]) == {"salt", "sodium"}                     # the other values are untouched


def test_frankfurt_energy_candidates_agree_with_the_label_and_never_touch_the_kj():
    c = run("8410320127363")
    assert len(c) == 2 and all(set(x["changes"]) == {"energy_kcal"} for x in c)
    assert any(close(v, 198, 0.01) for v in finals(c, "energy_kcal"))      # the label says 198 kcal
    assert all(x["values"]["energy_kj"] == 823.6 for x in c)               # the steward's proposal overwrote this correct value


def test_vinegar_has_the_per_100ml_kcal_and_the_revert_to_the_consistent_revision():
    c = run("8901595852321")
    assert any(x["kind"] == "derive" and close(x["values"]["energy_kcal"], 2.63, 0.01) for x in c)
    assert any(x["kind"] == "revert" and close(x["values"]["energy_kcal"], 2.67) for x in c)


def test_coconut_oil_is_repaired_by_the_serving_size_conversion_and_by_nothing_else():
    c = run("8906002661404")
    assert len(c) == 1 and c[0]["kind"] == "scale_all"
    v = c[0]["values"]
    assert close(v["fat"], 100, 0.01) and close(v["saturated_fat"], 93, 0.01) and close(v["energy_kcal"], 898.5, 0.01)


def test_granola_shortlist_holds_the_per_100g_values_derived_from_the_serving_figure():
    c = run("0677210091823")
    assert any(close(x["values"]["salt"], 0.636, 0.01) and close(x["values"]["sodium"], 0.2546, 0.01) for x in c)
    assert len(c) >= 3                                                      # an honest shortlist: the rules alone cannot say which side is wrong


def test_maggi_has_no_candidate_because_the_stored_values_break_no_rule():
    cur, _ = product("7613036892520")
    assert fc.violations(fc.clean(cur)) == set() and run("7613036892520") == []


def test_every_candidate_leaves_no_rule_violated_and_changes_something():
    for code in SAMPLE:
        for c in run(code):
            assert fc.violations(c["values"]) == set(), (code, c["description"])
            assert c["changes"], (code, c["description"])


def test_candidates_are_unique_and_sorted_by_how_few_fields_they_change():
    for code in SAMPLE:
        c = run(code)
        keys = [tuple(sorted((f, round(v, 3)) for f, v in x["values"].items())) for x in c]
        assert len(keys) == len(set(keys))
        sizes = [len(x["changes"]) for x in c]
        assert sizes == sorted(sizes)


def test_a_clean_record_gets_no_candidates_and_the_limit_is_respected():
    assert fc.candidates({"energy_kcal": 250.0, "energy_kj": 1046.0, "fat": 1.2, "carbohydrates": 52.4, "proteins": 7.4}) == []
    assert len(fc.candidates(*[product("0677210091823")[0], None, 55.0], max_candidates=2)) == 2


def test_a_whole_table_gram_milligram_slip_is_never_offered():
    """Dividing every value by 1000 passes every rule trivially (everything shrinks), so it must not be a candidate."""
    for code in SAMPLE:
        for c in run(code):
            assert "divide by 1000" not in c["description"] or "every value" not in c["description"]
