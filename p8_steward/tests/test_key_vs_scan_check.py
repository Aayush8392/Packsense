import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import key_vs_scan_check as kc  # noqa: E402

TABLE = "Nutritional Information per 100g\nEnergy 574 Kcal\nFat - 39g\nCarbohydrate - 49g\nProtein - 7g\nSodium - 0.9g\nSalt 1.2g"


def entry(**per100):
    return {"basis": "per 100 g", "serving": "", "per100": per100}


def test_a_clean_card_has_no_warning():
    assert kc.check_card(entry(energy_kcal=574, fat=39, carbohydrates=49, proteins=7, sodium=0.9, salt=1.2), TABLE) == []


def test_sodium_printed_in_g_but_keyed_as_mg_is_caught():            # the 0.9 g typed into the old mg-default box became 0.0009 g
    w = kc.check_card(entry(energy_kcal=574, fat=39, sodium=0.0009), TABLE)
    assert any(x.startswith("unit:") and "sodium" in x and "keyed in mg" in x for x in w)


def test_a_value_printed_in_mg_but_keyed_as_grams_is_caught():       # 'FAT 15.6mg' typed as 15.6 g
    text = "Nutritional information per 100g\nEnergy 445 Kcal\nFAT 15.6mg\nProtein 3.5g\nSugars 48.9g"
    w = kc.check_card(entry(energy_kcal=445, fat=15.6, proteins=3.5), text)
    assert any("fat" in x and "keyed in grams but the scan prints it in mg" in x for x in w)


def test_a_value_missing_from_the_scan_and_a_wrong_basis_are_caught():
    text = "Nutrition facts per serving\nEnergy 177 kcal\nProtein 13 g\nFat 3.6 g"
    w = kc.check_card({"basis": "per 100 g", "serving": "", "per100": {"energy_kcal": 177, "fat": 3.6, "proteins": 13, "carbohydrates": 26}}, text)
    assert any(x.startswith("basis:") for x in w)
    assert any("carbohydrates" in x and x.startswith("absent:") for x in w)


def test_per_serving_keys_are_compared_as_typed_and_the_ranges_warn():
    text = "Per serving (20 g)\nEnergy 76.4 kcal\nFat 1.5 g\nCarbohydrate 16.4 g"
    ok = {"basis": "per serving only (no per-100 column)", "serving": "20g", "per100": {"energy_kcal": 382.0, "fat": 7.5, "carbohydrates": 82.0}}
    assert kc.check_card(ok, text) == []
    w = kc.check_card(entry(energy_kcal=300, fat=50, carbohydrates=40, proteins=30, salt=63), "Energy 300 kcal fat 50 g carbohydrate 40 g protein 30 g salt 63 g")
    assert any(x.startswith("range:") and "salt" in x for x in w) and any("together above 105" in x for x in w)
