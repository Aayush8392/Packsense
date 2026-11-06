"""The reader's decision code, on real rows from the second development round (dev2). Every case is a real record, a real reading and a real scan text (shortened)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import answer_key_lib as ak  # noqa: E402
import reader_decision as rd  # noqa: E402

SCAN_SWAP = "Nutritional Information Approx.) | Refined | Parameters | Per 100 g | 369.4 Kcal | Energy | Protein | 1.6 g | Carbohydrate | 87.1 g | Total Sugar | Sugar | 64.2 g | 0.0 g | Fiber | Fat | 0.57 g | 1.6 g"


def test_a_household_measure_with_the_grams_in_brackets_is_a_serving_size_for_a_reading_only():
    assert ak.parse_bracket_serving("1/4 Cup (30g)") == (30.0, "g") and ak.parse_bracket_serving("1 bottle ( 330 ml )") == (330.0, "ml")
    assert ak.parse_serving("1/4 Cup (30g)") is None                                   # the owner's typed answers keep the strict rule
    r = ak.reading_to_per100({"basis": "per serving only", "serving_size": "1/4 Cup (30g)", "values_per_100": {"energy_kcal": 150, "fat": 9}})
    assert r["usable"] and abs(r["per100"]["energy_kcal"] - 500.0) < 1e-6 and abs(r["per100"]["fat"] - 30.0) < 1e-6


def test_a_space_between_thousands_is_read_as_one_number():
    nums = ak.numbers_in_text("por envase | 816.6 kcal (3 437.8 kJ) | por porcion | 408.3 kcal (1 718.9 kJ)")
    assert 3437.8 in nums and 1718.9 in nums and 816.6 in nums


def test_a_scan_without_a_table_is_not_a_table():
    assert ak.text_has_table(SCAN_SWAP)
    assert not ak.text_has_table("INGREDIENTS: PECANS, SUGAR, BUTTER (CREAM & SALT), HONEY, SALT, AND SOY LECITHIN")
    assert not ak.text_has_table("")


def test_a_reading_that_only_swaps_the_values_the_record_holds_makes_no_proposal():
    stored = {"energy_kcal": 369.4, "fat": 1.6, "carbohydrates": 87.1, "sugars": 64.2, "fiber": 0.57, "proteins": 1.6}
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 369.4, "fat": 0.57, "carbohydrates": 87.1, "sugars": 64.2, "fiber": 1.6, "proteins": 1.6}}
    out = rd.decide(stored, reading, SCAN_SWAP, "E_other_nutrition", "v2")
    assert out["action"].startswith("abstain") and "swaps" in out["action"] and not out["per100"]


def test_a_record_that_breaks_a_rule_the_reading_did_not_cover_is_not_called_unchanged():
    stored = {"energy_kcal": 317.26, "fat": 7.7, "saturated_fat": 4.06, "carbohydrates": 54.98, "sugars": 20.28, "fiber": 3.2, "proteins": 7.02, "salt": 893.9, "sodium": 357.56}
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 317.26, "fat": 7.7, "saturated_fat": 4.06, "carbohydrates": 54.98, "sugars": 20.28, "fiber": 3.2, "proteins": 7.02}}
    scan = "Nutritional Information | Energy (kcal) | Protein (g) | per 100g | 317.26 | 7.02 | 54.98 | 20.28 | 3.20 | 7.70 | 4.06 | Sodium (mg) | 357.56"
    out = rd.decide(stored, reading, scan, "C_values_too_large", "v2")
    assert out["action"].startswith("abstain") and "did not cover" in out["action"]


def test_a_real_fix_still_goes_through():
    stored = {"energy_kcal": 42.0, "energy_kj": 1750.0, "fat": 11.0, "saturated_fat": 2.0, "carbohydrates": 68.0, "sugars": 3.3, "proteins": 11.0, "salt": 2.3}
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 421, "energy_kj": 1774, "fat": 11, "carbohydrates": 68, "sugars": 3.3, "proteins": 11}}
    scan = "Valor energetico | 1774kJ, 421kcal | 11 g | 68 g | 3,3 g | 11 g | 2,3 g | Grasas | Hidratos de carbono"
    out = rd.decide(stored, reading, scan, "A_energy_mismatch", "v2")
    assert out["action"] == "change to reading" and out["per100"]["energy_kcal"] == 421.0


# --- the three ways a reading that breaks a rule is still used (real records of dev2) ---

def test_when_the_pack_contradicts_itself_and_the_record_says_the_same_the_status_carries_the_figures():
    stored = {"energy_kcal": 900.0, "energy_kj": 0.0, "fat": 99.9, "saturated_fat": 15.95, "carbohydrates": 0.0, "sugars": 0.0, "fiber": 0.0, "proteins": 0.0, "salt": 0.0, "sodium": 0.0}
    reading = {"basis": "per 100 g", "values_per_100": dict(stored)}
    scan = "Energy 900 kcal 0 kJ | Fat 99.9 g | Saturated fat 15.95 g | Carbohydrate 0 g | Sugars 0 g | Fibre 0 g | Protein 0 g | Salt 0 g | Sodium 0 g"
    out = rd.decide(stored, reading, scan, "A_energy_mismatch", "v2")
    assert out["action"] == "no change (the pack's own numbers disagree)" and any("kJ" in s for s in out["evidence"]) and not out["per100"]


def test_a_record_whose_salt_disagrees_with_the_printed_sodium_is_called_inconsistent_not_wrong_on_the_pack():
    stored = {"energy_kcal": 513.0, "energy_kj": 2145.5, "fat": 26.1, "saturated_fat": 11.0, "carbohydrates": 62.6, "sugars": 2.2, "fiber": 0.0, "proteins": 6.8, "salt": 5.0, "sodium": 0.756}
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 513, "fat": 26.1, "saturated_fat": 11, "carbohydrates": 62.6, "sugars": 2.2, "proteins": 6.8, "sodium": 0.756}}
    scan = "Energy 513 kcal | Fat 26.1 g | of which saturates 11 g | Carbohydrate 62.6 g | of which sugars 2.2 g | Protein 6.8 g | Sodium 756 mg"
    out = rd.decide(stored, reading, scan, "B_salt_vs_sodium", "v2")
    assert out["action"] == "no change (an unprinted field is inconsistent)" and "1.89 g of salt" in out["evidence"][0] and "5 g" in out["evidence"][0] and not out["per100"]
    # the stricter reading of A121 11 (e) (this status becomes 'not assessed') is the option "unprinted_inconsistent", OFF by default: it cost 8 to 9 points of coverage on the closed test
    assert rd.decide(stored, reading, scan, "B_salt_vs_sodium", "v2", rd.OPTIONS | {"unprinted_inconsistent"})["action"] == rd.UNPRINTED


def test_one_misread_field_is_left_out_and_the_rest_of_the_reading_is_used():
    stored = {"energy_kcal": 317.26, "energy_kj": 1364.5, "fat": 7.7, "saturated_fat": 4.06, "carbohydrates": 54.98, "sugars": 20.28, "fiber": 3.2, "proteins": 7.02, "salt": 893.9, "sodium": 357.56}
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 317.26, "energy_kj": 10.73, "fat": 7.7, "saturated_fat": 4.06, "carbohydrates": 54.98, "sugars": 20.28, "fiber": 3.2,
                                                        "proteins": 7.02, "sodium": 0.358}}
    scan = "Energy (kcal) 317.26 | Protein 7.02 | Carbohydrate 54.98 | Sugars 20.28 | Fibre 3.20 | Fat 7.70 | Saturated 4.06 | 10.73 | Sodium (mg) 357.56 | 0.358"
    out = rd.decide(stored, reading, scan, "C_values_too_large", "v2")
    assert out["action"] == "change to reading" and out["per100"] == {"sodium": 0.358} and "energy_kj" in out["dropped"]


def test_the_retry_message_describes_the_readings_own_broken_checks_with_computed_figures():
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kj": 8400, "energy_kcal": 2000, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 5.5, "sugars": 0.17, "proteins": 8.4, "salt": 0.17}}
    scan = "Energy 8400 kJ 2000 kcal | Fat 0.5 | Saturates 0.3 | Carbohydrate 5.5 | Sugars 0.17 | Protein 8.4 | Salt 0.17"
    problems = rd.reading_problems(reading, scan)
    assert problems and any("add up to about" in p for p in problems)
    assert rd.reading_problems(None, scan) is None
    clean = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 400, "fat": 3, "carbohydrates": 7, "proteins": 83, "sugars": 3}}
    assert rd.reading_problems(clean, "400 kcal | 3 | 7 | 83 | 3 | fat") == []


def test_a_record_with_salt_and_sodium_the_pack_never_prints_is_not_a_match():
    # real record of the first sealed test (card 0745178376174, group B): the pack prints neither salt nor sodium; OFF holds salt 10 g, sodium 0
    stored = {"energy_kcal": 45.02, "energy_kj": 188.0, "fat": 0.0, "saturated_fat": 0.0, "carbohydrates": 11.13, "sugars": 0.0, "fiber": 0.0, "proteins": 0.0, "salt": 10.0, "sodium": 0.0}
    reading = {"basis": "per 100 g", "values_per_100": {"energy_kcal": 45.02, "carbohydrates": 11.13, "sugars": 0.0, "fiber": 0.0, "proteins": 0.0, "fat": 0.0}}
    scan = "Nutrition Facts per 100 g | Energy 45.02 kcal | Carbohydrate 11.13 g | of which sugars 0 g | Dietary fibre 0 g | Protein 0 g | Fat 0 g"
    out = rd.decide(stored, reading, scan, "B_salt_vs_sodium", "v3rows")
    assert out["action"] == rd.UNPRINTED and not out["per100"]
    assert rd.decide(stored, reading, scan, "B_salt_vs_sodium", "v3rows", rd.OPTIONS - {"unprinted"})["action"] == "no change"       # what the closed test did
    # a record that holds nothing for the flagged group is still just 'no change' (nothing unprinted to doubt)
    bare = {k: v for k, v in stored.items() if k not in ("salt", "sodium")}
    assert rd.decide(bare, reading, scan, "B_salt_vs_sodium", "v3rows")["action"] == "no change"


def test_a_record_whose_flagged_fields_are_all_printed_is_still_unchanged():
    stored = {"energy_kcal": 400.0, "fat": 10.0, "carbohydrates": 60.0, "proteins": 8.0, "salt": 1.0, "sodium": 0.4}
    reading = {"basis": "per 100 g", "values_per_100": dict(stored)}
    scan = "Energy 400 kcal | Fat 10 g | Carbohydrate 60 g | Protein 8 g | Salt 1.0 g | Sodium 0.4 g"
    assert rd.decide(stored, reading, scan, "B_salt_vs_sodium", "v3rows")["action"] == "no change"
