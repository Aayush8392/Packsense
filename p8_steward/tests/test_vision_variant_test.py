import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vision_variant_test as v  # noqa: E402

T = {"fat": 3.0, "carbohydrates": 20.0, "proteins": 5.0}
WRONG = {"fat": 30.0, "carbohydrates": 20.0, "proteins": 5.0}


def case(code, who, truth):
    return {"code": code, "who": who, "truth": truth, "basis": "per 100 g"}


def test_vision_instruction_is_the_text_instruction_with_only_the_input_changed():
    s = v.vision_system()
    assert "photo" in s and "<ocr>" not in s and "OCR text" not in s and "ONLY numbers you can clearly read" in s and "values_per_100" in s


def test_rules_and_disagreement_are_counted_as_agreed():
    cases = [case("a", "both", T), case("b", "hybrid", T), case("c", "contributor", T), case("d", "neither", None)]
    text = {"a": T, "b": T, "c": WRONG, "d": T}
    vision = {"a": T, "b": WRONG, "c": T, "d": T}
    hybrid = {"a": T, "b": T, "c": WRONG, "d": T}
    e = v.evaluate(cases, text, vision, hybrid)
    assert e["known_right"] == 3 and e["text_right"] == 2 and e["vision_right"] == 2
    assert e["narrow"] == {"shown": 4, "right": 2}                                      # all four have hybrid = text reading; only a and b have the hybrid right
    assert e["rule1"] == {"shown": 2, "right": 1}                                      # a (both) counts, d is shown but wrong; b dropped by the photo
    assert e["rule2"] == {"shown": 2, "right": 1}                                      # a and d agree; d has no right table so it is wrong
    assert e["disagree"] == {"n": 2, "text_right": 1, "vision_right": 1, "both_wrong_or_unknown": 0}


def test_wilson_matches_the_known_value():
    lo, hi = v.wilson(30, 33)
    assert abs(lo - 0.764) < 0.005 and abs(hi - 0.969) < 0.01
