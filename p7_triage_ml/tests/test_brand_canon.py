"""Brand canonicalisation on real brand strings (taken from the run of 2026-11-03 over the products we hold, with their real product counts)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "analysis"))
import brand_canon as bc  # noqa: E402

REAL = {"bonduelle": 92, "bonduell": 3, "çiloğlu": 1, "çiloglu": 1, "ciloglu": 1, "cal & gary's": 3, "cal & gary’s": 1, "foothills creamery": 2, "foothills creamery ltd.": 1,
        "piątnica": 18, "piatnica": 1, "stonefire": 10, "stone fire": 1, "edwards": 5, "edward’s": 1, "essential everyday": 25, "essential everday": 1}


def test_the_key_ignores_accents_quotes_spacing_punctuation_and_trailing_legal_words():
    assert bc.brand_key("çiloğlu") == bc.brand_key("çiloglu") == bc.brand_key("ciloglu")
    assert bc.brand_key("cal & gary's") == bc.brand_key("cal & gary’s")
    assert bc.brand_key("foothills creamery ltd.") == bc.brand_key("foothills creamery")
    assert bc.brand_key("stone fire") == bc.brand_key("stonefire") == "stonefire"
    assert bc.brand_key("piątnica") == bc.brand_key("piatnica")
    assert bc.brand_key("") == "" and bc.brand_key(None) == ""


def test_a_group_is_named_by_its_most_frequent_string_and_a_lone_string_stays_itself():
    m = bc.group_brands(REAL)
    assert m["bonduell"] == ("bonduelle", "close") and m["bonduelle"] == ("bonduelle", "same")
    assert m["piatnica"] == ("piątnica", "key") and m["foothills creamery ltd."] == ("foothills creamery", "key")
    assert m["çiloglu"][0] == m["ciloglu"][0] == m["çiloğlu"][0]
    assert m["essential everday"] == ("essential everyday", "close")


def test_regrouping_the_canonical_names_changes_nothing_and_no_count_is_lost():
    m = bc.group_brands(REAL)
    canon = {c: sum(n for r, n in REAL.items() if m[r][0] == c) for c, _ in set(m.values())}
    again = bc.group_brands(canon)
    assert all(v == (k, "same") for k, v in again.items()) and sum(canon.values()) == sum(REAL.values())


def test_a_string_that_is_only_a_legal_word_is_not_emptied():
    assert bc.brand_key("ltd") == "ltd" and bc.brand_key("the") == "the"
