import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import dev_ocr_reader as dr  # noqa: E402
import photo_method as pm  # noqa: E402
import vision_variant_test as vv  # noqa: E402

TEXT = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
VALUES = {"energy_kcal": 90, "energy_kj": 376, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
STORED = {"energy_kcal": 90.0, "energy_kj": 376.0, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}


def entry(values):
    return {"reading": {"basis": "per 100 g", "serving_size": None, "values_per_100": dict(values)}}


def decide(text_values=VALUES, photo_values=VALUES, text=TEXT, stored=STORED, **kw):
    return pm.decide("c", entry(text_values) if text_values is not None else None, entry(photo_values) if photo_values is not None else None, text, stored, **kw)


def test_the_method_reuses_the_frozen_pieces_and_keeps_the_candidate_list_fixed():
    assert pm.text_system() is dr.SYSTEMS["v3rows"] and pm.photo_system() == vv.vision_system()
    assert pm.LINE_TYPES == ("rule2", "rule1", "differ", "match") and pm.PHOTO_LONG_SIDE == 1600 and pm.MODEL == "gemini-3.5-flash-lite"


def test_agreeing_readings_that_match_the_stored_values_give_a_match_line():
    d = decide()
    assert d["silence"] is None and d["rule2"] and d["differs"] is False and d["types"] == ["rule2", "match"] and d["table"]["fat"] == 0.5


def test_agreeing_readings_that_differ_from_the_stored_values_give_a_differ_line_naming_the_fields():
    d = decide(stored={**STORED, "fat": 5.0, "salt": 0.6})
    assert d["silence"] is None and d["differs"] is True and d["differing_fields"] == ["fat", "salt"] and d["types"] == ["rule2", "differ"]


def test_a_field_the_table_has_and_the_record_lacks_is_a_difference_but_not_the_reverse():
    assert pm.differing_fields({"fat": 0.5, "salt": 0.06}, {"fat": 0.5}) == ["salt"]
    assert pm.differing_fields({"fat": 0.5}, {"fat": 0.5, "salt": 0.06}) == []


def test_disagreement_is_silence_and_never_falls_back_to_the_text_reading():
    d = decide(photo_values={**VALUES, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0})
    assert d["silence"] == "no_agreement" and d["table"] is None and d["types"] == []


def test_each_missing_input_is_its_own_silence():
    assert decide(has_photo=False)["silence"] == "no_photo"
    assert decide(text="no table here")["silence"] == "no_ocr_table"
    assert decide(text_values=None)["silence"] == "text_unusable"
    assert decide(photo_values=None)["silence"] == "photo_unusable"
    assert decide(photo_values={"fat": 0.5, "salt": 0.06})["silence"] == "photo_unusable"                 # fewer than three fields


def test_a_photo_number_the_ocr_text_does_not_print_is_dropped_by_the_guard():
    d = decide(photo_values={**VALUES, "fiber": 7.7})
    assert d["silence"] is None and "fiber" not in d["table"]


def test_rule1_needs_the_hybrid_to_agree_with_the_text_and_the_photo_to_agree_with_the_hybrid():
    assert decide(hybrid=dict(STORED))["types"] == ["rule2", "match", "rule1"]
    assert decide()["rule1"] is False                                                               # no hybrid table: rule 1 cannot hold
    wrong = {**STORED, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0}
    assert decide(hybrid=wrong)["rule1"] is False


def test_rule1_alone_still_shows_the_photo_table():
    t = {**VALUES, "sugars": 8.9}                                   # a printed number, in the wrong row: 7 of 8 fields agree with the photo reading, under the 90% bar
    hybrid = {"fat": 0.5, "carbohydrates": 8.9, "proteins": 12.4}   # shares only three fields, and agrees with both readings on them
    d = decide(text_values=t, hybrid=hybrid)
    assert d["rule2"] is False and d["rule1"] is True and d["silence"] is None
    assert d["types"] == ["rule1"] and d["table"]["sugars"] == 6.5
