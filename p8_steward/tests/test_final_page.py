"""Tests for the final-block draw, the one-line page and the scoring (final_page.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import final_page as fp  # noqa: E402


def lines(n=149, no_kcal=()):
    return {f"{i:013d}": ({"fat": 1.0} if f"{i:013d}" in no_kcal else {"energy_kcal": 100 + i, "fat": 1.0}) for i in range(n)}


def test_the_draw_is_repeatable_and_has_100_sampled_lines_and_15_decoys_outside_the_sample():
    d1, d2 = fp.draw(lines()), fp.draw(lines())
    assert d1 == d2
    assert len(d1["sample"]) == 100 and len(d1["decoys"]) == 15 and not set(d1["sample"]) & set(d1["decoys"])
    assert sorted(d1["order"]) == sorted(d1["sample"] + list(d1["decoys"])) and len(d1["order"]) == 115


def test_a_decoy_shows_the_kcal_value_times_one_and_a_half_rounded_and_never_a_line_without_kcal():
    base = lines()
    d = fp.draw(base)
    for c, v in d["decoys"].items():
        assert v["original_kcal"] == base[c]["energy_kcal"] and v["shown_kcal"] == round(base[c]["energy_kcal"] * 1.5)
    none = fp.draw(lines(no_kcal={c for c in list(lines())[100:]}))
    assert none["decoys"] == {} or all(lines()[c].get("energy_kcal") is not None for c in none["decoys"])


def test_the_sample_is_the_first_100_in_hash_order():
    base = lines()
    assert fp.draw(base)["sample"] == sorted(base, key=lambda c: fp.h("final-judge:", c))[:100]


def test_scoring_counts_the_sample_only_catches_decoys_and_leaves_excluded_packs_out():
    key = {"a": "sample", "b": "sample", "c": "sample", "d": "sample", "x": "decoy", "y": "decoy"}
    ans = {"a": "right", "b": "right", "c": "wrong", "d": "unsure", "x": "wrong", "y": "right"}
    s = fp.score(ans, key)
    assert (s["right"], s["wrong"], s["unsure"]) == (2, 1, 1)
    assert s["decoys"]["caught_as_wrong"] == 1 and s["decoys"]["missed_as_right"] == 1
    e = fp.score(ans, key, {"c": "two columns"})
    assert (e["right"], e["wrong"]) == (2, 0) and e["excluded_apart"]["c"]["answer_given"] == "wrong"


def test_the_page_has_one_table_three_choices_a_dark_toggle_and_the_prefetch_of_the_next_two_photos():
    item = fp.build_item({"code": "1", "serving_size": ""}, {"energy_kcal": 100}, None, None)
    page = fp.render([item], {"1": "https://images.openfoodfacts.org/x.full.jpg"})
    assert 'id="ta"' not in page.split("</style>")[0] and 'id="tb"' not in page and 'id="tc"' not in page
    assert '"right"' in page and '"wrong"' in page and '"unsure"' in page and 'id="dark"' in page and "prefers-color-scheme" in page
    assert "prefetch(i+1);prefetch(i+2)" in page
