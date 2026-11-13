"""Tests for the stage 2 judging tool (nightly/stage2_judge.py): the draw, the decoys, the page items and the pass rule. Digit barcodes and made-up values test the rules, not the data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
from nightly import stage2_judge as sj  # noqa: E402

NIGHT = "2026-11-14"


def lines(n, night=NIGHT, start=10000000):
    return {str(start + i): {"code": str(start + i), "night": night, "line_type": "match", "statement": "checked", "values": {"energy_kcal": 100.0 + i, "fat": 1.5, "salt": 0.5}} for i in range(n)}


def test_the_draw_is_repeatable_and_sized():
    d1, d2 = sj.draw(lines(80), NIGHT), sj.draw(dict(reversed(list(lines(80).items()))), NIGHT)
    assert d1 == d2
    assert (len(d1["sample"]), len(d1["extension"]), len(d1["decoys"])) == (30, 10, 5)
    assert not set(d1["sample"]) & set(d1["extension"]) and not set(d1["decoys"]) & (set(d1["sample"]) | set(d1["extension"]))


def test_only_lines_of_the_night_with_values_are_drawn():
    mixed = {**lines(50), **lines(20, night="2026-11-13", start=20000000)}
    mixed["30000000"] = {"night": NIGHT, "values": {}}
    mixed["30000001"] = "oops"
    d = sj.draw(mixed, NIGHT)
    assert d["lines_on_night"] == 50 and all(c.startswith("1") for c in d["sample"] + d["extension"] + list(d["decoys"]))


def test_a_decoy_shows_kcal_times_one_and_a_half_and_a_line_without_kcal_is_never_a_decoy():
    ls = lines(60)
    first_rest = sorted(ls, key=lambda c: sj.h("stage2-judge:", c))[40:]
    for c in first_rest[:10]:
        del ls[c]["values"]["energy_kcal"]
    d = sj.draw(ls, NIGHT)
    assert all(ls[c]["values"].get("energy_kcal") is not None for c in d["decoys"])
    c, v = next(iter(d["decoys"].items()))
    assert v["shown_kcal"] == round(v["original_kcal"] * 1.5)
    assert sj.item(c, d["values"][c], d["decoys"])["A"]["energy_kcal"] == v["shown_kcal"]


def test_the_page_order_hides_the_key_and_the_extension_is_optional():
    d = sj.draw(lines(80), NIGHT)
    assert len(sj.page_codes(d, False)) == 35 and len(sj.page_codes(d, True)) == 45
    assert sj.page_codes(d, False) != sorted(sj.page_codes(d, False))      # not in barcode order
    it = sj.item("10000001", {"fat": 1.23456, "salt": None}, {})
    assert set(it) == {"code", "A", "B", "stored_before", "serving", "serving_g", "serving_src", "basis_hint", "glossary"}
    assert it["A"] == {"fat": 1.235} and it["B"] == {} and it["stored_before"] == {}     # no stored values, no model, no line type


def test_the_page_renders():
    import final_page as fp
    d = sj.draw(lines(80), NIGHT)
    items = [sj.item(c, d["values"][c], d["decoys"]) for c in sj.page_codes(d, False)]
    page = fp.render(items, {it["code"]: "" for it in items}, sj.WHICH)
    assert "Does this line match the pack?" in page and len(page) > 5000


def answers(right, wrong, unsure, dright=0, dwrong=5, dunsure=0, n=30):
    key = {f"s{i}": "sample" for i in range(n)} | {f"d{i}": "decoy" for i in range(5)}
    a = {}
    for i, v in enumerate(["right"] * right + ["wrong"] * wrong + ["unsure"] * unsure):
        a[f"s{i}"] = v
    for i, v in enumerate(["right"] * dright + ["wrong"] * dwrong + ["unsure"] * dunsure):
        a[f"d{i}"] = v
    return a, key


def test_the_pass_rule():
    assert sj.score(*answers(27, 3, 0))["verdict"] == "PASS"
    assert sj.score(*answers(26, 4, 0))["verdict"] == "FAIL"
    assert sj.score(*answers(25, 0, 5))["verdict"] == "PASS"            # 25 judged, all right, 5 can't tell
    assert sj.score(*answers(23, 2, 5))["verdict"] == "PASS"            # 23 of 25 = 92%
    assert sj.score(*answers(22, 3, 5))["verdict"] == "FAIL"            # 22 of 25 = 88%
    assert sj.score(*answers(20, 4, 6))["verdict"].startswith("EXTEND")  # only 24 judged
    assert sj.score(*answers(30, 0, 0, dright=2, dwrong=3))["verdict"].startswith("VOID")
    assert sj.score(*answers(30, 0, 0, dright=1, dwrong=4))["verdict"] == "PASS"   # 4 of 5 decoys caught is enough


def test_an_unanswered_page_is_incomplete():
    a, key = answers(27, 3, 0)
    del a["s5"]
    assert sj.score(a, key)["verdict"].startswith("incomplete")
