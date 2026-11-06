"""Reading what the owner types for one answer-key card (item 23)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import answer_key_lib as ak  # noqa: E402


def test_the_example_line_is_read_in_full_and_milligrams_become_grams():
    r = ak.parse("kcal 168, kj 701, fat 9.7, sat 1.7, carbs 0, sugars 0, fibre 0, protein 20.1, salt 2.55, sodium 445mg")
    assert r["errors"] == [] and r["approx"] == []
    assert r["values"] == {"energy_kcal": 168.0, "energy_kj": 701.0, "fat": 9.7, "saturated_fat": 1.7, "carbohydrates": 0.0, "sugars": 0.0, "fiber": 0.0,
                           "proteins": 20.1, "salt": 2.55, "sodium": 0.445}


def test_zeros_after_the_decimal_point_comma_decimals_and_leading_point_all_work():
    r = ak.parse("sodium 0.045, salt 0,10, fat .5, sat 2.")
    assert r["errors"] == [] and r["values"] == {"sodium": 0.045, "salt": 0.1, "fat": 0.5, "saturated_fat": 2.0}


def test_units_with_or_without_a_space_and_a_few_separators():
    r = ak.parse("sodium=445 mg; salt: 1.1 g\nfat 3mg")
    assert r["values"] == {"sodium": 0.445, "salt": 1.1, "fat": 0.003} and r["errors"] == []
    assert ak.parse("sodium 445 ug")["values"]["sodium"] == 0.000445


def test_a_less_than_figure_keeps_its_number_and_is_marked_approximate():
    r = ak.parse("fat <0.5, protein ~4.9 g, salt <=0.01")
    assert r["values"] == {"fat": 0.5, "proteins": 4.9, "salt": 0.01} and sorted(r["approx"]) == ["fat", "proteins", "salt"]


def test_an_unknown_word_a_wrong_unit_a_duplicate_and_junk_are_reported_never_dropped():
    r = ak.parse("kcall 100, kj 700 g, fat 1, fat 2, sodium abc, vitamin c 10")
    assert r["values"] == {"fat": 1.0}
    assert len(r["errors"]) == 5, r["errors"]


def test_energy_units_must_fit_the_field_and_blank_input_is_empty_not_an_error():
    assert ak.parse("kcal 168 kcal, kj 701 kj")["values"] == {"energy_kcal": 168.0, "energy_kj": 701.0}
    assert ak.parse("kcal 168 kj")["errors"]
    assert ak.parse("") == {"values": {}, "approx": [], "errors": []} and ak.parse(None)["values"] == {}


def test_format_line_round_trips_numbers_so_earlier_answers_can_be_carried_over():
    values = {"energy_kcal": 168.0, "energy_kj": 701.0, "fat": 9.7, "sodium": 0.445, "salt": 1.1125}
    assert ak.parse(ak.format_line(values))["values"] == values


def test_each_box_is_read_for_its_own_field_with_units_decimals_and_blanks():
    r = ak.parse_boxes({"k_energy_kcal": "168", "k_sodium": "445mg", "k_salt": "0,10", "k_fat": "<0.5", "k_sugars": "0.045", "k_fiber": "", "k_proteins": "  "})
    assert r["errors"] == []
    assert r["values"] == {"energy_kcal": 168.0, "sodium": 0.445, "salt": 0.1, "fat": 0.5, "sugars": 0.045} and r["approx"] == ["fat"]


def test_a_box_reports_what_it_cannot_read_with_the_box_name_and_a_wrong_energy_unit_is_refused():
    r = ak.parse_boxes({"k_fat": "abc", "k_energy_kj": "701 kcal", "k_unknown": "5"})
    assert r["values"] == {} and len(r["errors"]) == 2 and r["errors"][0].startswith("k_fat")


def task(basis, boxes, serving="", code="1"):
    results = [{"from_name": "basis", "type": "choices", "value": {"choices": [basis]}}]
    results += [{"from_name": k, "type": "textarea", "value": {"text": [v]}} for k, v in boxes.items()]
    if serving:
        results.append({"from_name": "serving_size", "type": "textarea", "value": {"text": [serving]}})
    return {"data": {"code": code, "group": "A_energy_mismatch"}, "annotations": [{"result": results}]}


def test_serving_sizes_in_g_or_ml_are_read_and_the_rest_are_not():
    assert ak.parse_serving("30g") == (30.0, "g") and ak.parse_serving(" 2,7 g ") == (2.7, "g") and ak.parse_serving("15 ML") == (15.0, "ml")
    assert ak.parse_serving("1 bottle") is None and ak.parse_serving("14g and 25g") is None and ak.parse_serving("") is None


def test_a_per_100_card_is_usable_as_typed_and_a_per_serving_card_is_scaled_to_100():
    e = ak.key_entry(task("per 100 g", {"k_fat": "9.7", "k_sodium": "445mg"}))
    assert e["usable"] and e["per100"] == {"fat": 9.7, "sodium": 0.445} and e["unit"] == "g"
    e = ak.key_entry(task("per serving only (no per-100 column)", {"k_energy_kcal": "5", "k_sodium": "420mg"}, serving="3.8g"))
    assert e["usable"] and abs(e["per100"]["energy_kcal"] - 131.578947) < 1e-5 and abs(e["per100"]["sodium"] - 11.052632) < 1e-5


def test_cards_that_cannot_be_used_keep_their_reason_and_nothing_is_guessed():
    assert not ak.key_entry(task("cannot read the table", {"k_fat": "4"}))["usable"]
    e = ak.key_entry(task("per serving only (no per-100 column)", {"k_fat": "0"}, serving="1 bottle"))
    assert not e["usable"] and "not in g or ml" in e["reason"]
    assert not ak.key_entry(task("per 100 g", {}))["usable"]
    e = ak.key_entry(task("per 100 g", {"k_fat": "abc"}))
    assert not e["usable"] and "could not be read" in e["reason"]


def test_build_key_leaves_out_unanswered_tasks():
    answered = task("per 100 g", {"k_fat": "1"}, code="A")
    unanswered = {"data": {"code": "B"}, "annotations": []}
    assert list(ak.build_key([answered, unanswered])) == ["A"]


def test_a_value_is_right_within_ten_percent_or_a_small_absolute_allowance():
    assert ak.field_matches("energy_kcal", 112.0, 112.0) and ak.field_matches("energy_kcal", 118.0, 112.0) and not ak.field_matches("energy_kcal", 141.4, 198.0)
    assert ak.field_matches("fat", 0.0, 0.04) and not ak.field_matches("fat", 0.5, 0.0) and not ak.field_matches("sodium", 440.0, 0.44)
    assert not ak.field_matches("fat", None, 1.0)


def test_matches_key_compares_only_fields_both_sides_have_and_needs_at_least_one():
    key = {"energy_kcal": 198.0, "fat": 15.0, "sodium": 1.0}
    assert ak.matches_key({"energy_kcal": 196.8, "fat": 15.0}, key) == {"compared": 2, "wrong": [], "match": True}
    assert ak.matches_key({"energy_kcal": 141.4, "fat": 15.0}, key)["wrong"] == ["energy_kcal"]
    assert ak.matches_key({}, key) == {"compared": 0, "wrong": [], "match": False}


def test_a_repair_is_judged_only_on_the_fields_its_flag_group_is_about():
    key = {"salt": 0.52, "sodium": 0.21, "fiber": 6.5}
    record = {"salt": 0.52, "sodium": 0.21, "fiber": 7.9}              # fibre differs from the pack but no salt/sodium flag is about it
    assert ak.matches_key(record, key)["match"] is False
    assert ak.matches_key_for_group(record, key, "B_salt_vs_sodium") == {"compared": 2, "wrong": [], "match": True}
    assert ak.matches_key_for_group(record, key, "E_other_nutrition")["wrong"] == ["fiber"]


def test_a_reading_becomes_per_100_values_by_the_same_rules_as_the_key():
    r = ak.reading_to_per100({"basis": "per 100 g", "values_per_100": {"energy_kcal": 112, "fat": 2.1, "bogus": 5, "salt": "1.5", "sodium": True}})
    assert r["usable"] and r["per100"] == {"energy_kcal": 112.0, "fat": 2.1}                       # an unknown field, a text number and a boolean are dropped
    r = ak.reading_to_per100({"basis": "per serving only", "serving_size": "3.8 g", "values_per_100": {"energy_kcal": 5}})
    assert r["usable"] and abs(r["per100"]["energy_kcal"] - 131.578947) < 1e-5
    assert not ak.reading_to_per100({"basis": "per serving only", "serving_size": "1 bottle", "values_per_100": {"fat": 0}})["usable"]
    assert not ak.reading_to_per100({"basis": "unclear", "values_per_100": {"fat": 1}})["usable"]
    assert ak.reading_to_per100({"basis": "per 100 g", "values_per_100": {}})["reason"] == "no numbers read"


def test_numbers_in_text_reads_the_forms_a_pack_prints():
    n = ak.numbers_in_text("Energie 153kJ, glucides 8-9g, sucres 7,6 g, sel 0.12 g, 2.307 kJ, 445 mg")
    assert {153.0, 8.9, 7.6, 0.12, 2307.0, 2.307, 445.0, 8.0}.issubset(n)


def test_a_value_is_grounded_when_printed_and_not_when_invented():
    text = "Per 100 g Energy 474kJ 112kcal Fat 2.1g Salt 1.50g Sodium 445mg"
    kept, dropped = ak.grounded_values({"energy_kj": 474, "energy_kcal": 112, "fat": 2.1, "salt": 1.5, "sodium": 0.445, "sugars": 8.2, "proteins": 21.7}, text)
    assert dropped == ["sugars", "proteins"] and set(kept) == {"energy_kj", "energy_kcal", "fat", "salt", "sodium"}
    kept, dropped = ak.grounded_values({"energy_kj": 0.474}, "474 kJ")                    # energy is never rescaled by 1000
    assert dropped == ["energy_kj"]


# --- the test form: sodium box in mg, no digit hotkeys (owner, 2026-11-05) ---------------------------------------------------------------------------

def test_sodium_mg_box_reads_a_bare_number_as_milligrams_and_respects_an_explicit_unit():
    r = ak.parse_boxes({"k_sodium_mg": "445"})
    assert r["values"] == {"sodium": 0.445} and not r["errors"]
    assert ak.parse_boxes({"k_sodium_mg": "0.445g"})["values"] == {"sodium": 0.445}
    assert ak.parse_boxes({"k_sodium_mg": "445 mg"})["values"] == {"sodium": 0.445}
    assert ak.parse_boxes({"k_sodium_mg": "12,5"})["values"] == {"sodium": 0.0125}
    r = ak.parse_boxes({"k_sodium_mg": "<5"})
    assert r["values"] == {"sodium": 0.005} and r["approx"] == ["sodium"]
    assert ak.parse_boxes({"k_sodium_mg": ""})["values"] == {}


def test_the_old_sodium_box_keeps_grams_so_earlier_projects_read_the_same():
    assert ak.parse_boxes({"k_sodium": "0.022"})["values"] == {"sodium": 0.022}
    assert ak.parse_boxes({"k_sodium": "445mg"})["values"] == {"sodium": 0.445}
    assert ak.with_default_unit("k_fat", "9.7") == "9.7"              # only the sodium mg box has a default unit


def test_the_form_config_has_the_unit_required_sodium_box_and_gives_every_choice_a_non_digit_hotkey():
    import re
    from pathlib import Path
    xml = (Path(__file__).resolve().parents[1] / "labelling" / "answer_key_boxes_config.xml").read_text(encoding="utf-8")
    assert 'name="k_sodium_unit"' in xml and 'name="k_sodium"' not in xml and 'name="k_sodium_mg"' not in xml      # the fresh set's sodium box takes its unit from the owner (the first test's mg-default box is gone from the form)
    choices = re.findall(r"<Choice [^>]*>", xml)
    assert len(choices) == 4
    for c in choices:
        m = re.search(r'hotkey="([^"]+)"', c)
        assert m and not m.group(1).isdigit(), c                   # a bare digit hotkey (the numpad keys 1 to 4) switched the column while typing numbers
    for box in ak.BOX_NAMES:
        if box not in ("k_sodium", "k_sodium_mg"):         # the two older sodium boxes stay readable for projects 36 to 40, but are not in the form
            assert f'name="{box}"' in xml, box


def test_the_unit_required_sodium_box_refuses_a_bare_number_and_respects_an_explicit_unit():
    bare = ak.parse_boxes({"k_sodium_unit": "0.9"})
    assert bare["values"] == {} and "unit (mg or g) is required" in bare["errors"][0]
    assert ak.parse_boxes({"k_sodium_unit": "0.9 g"})["values"] == {"sodium": 0.9}
    assert ak.parse_boxes({"k_sodium_unit": "445mg"})["values"] == {"sodium": 0.445}
    assert ak.parse_boxes({"k_sodium_unit": ""})["errors"] == []                 # a blank box means 'not printed'
    assert ak.parse_boxes({"k_sodium_mg": "445"})["values"] == {"sodium": 0.445}   # the first test's form still reads the same
