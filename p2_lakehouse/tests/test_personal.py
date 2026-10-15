"""Stateless handling of personal data and values: hashing, own-handle redaction, scrubbing, fingerprint, parsing, shape checks.

Identities in these tests are the fixtures' placeholders (user_0001 ...), which stand in for real contributor names; the
texts being scrubbed use shapes that occur in real records.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, personal  # noqa: E402

C = contract.load()
KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
OTHER_KEY = "another-test-key-0000000000000000000000000000000000000"
SENTINEL = C["own_handle_redaction"]["sentinel"]
UNITS = C["parsing"]["units"]
PATTERNS = personal.compile_patterns(C)


# ---- hashing -----------------------------------------------------------------------------------------------------------

def test_normalise_ignores_case_edges_and_width():
    assert personal.normalise("  User_0001 ") == "user_0001"
    assert personal.normalise("ＵＳＥＲ_0001") == "user_0001"


def test_hmac_is_64_hex_deterministic_key_dependent_and_case_insensitive():
    h = personal.hmac_hex(KEY, "user_0001")
    assert len(h) == 64 and int(h, 16) >= 0 and h == personal.hmac_hex(KEY, "User_0001")
    assert h != personal.hmac_hex(OTHER_KEY, "user_0001") and h != personal.hmac_hex(KEY, "user_0002")


def test_hash_value_shapes():
    assert personal.hash_value(KEY, None) is None and personal.hash_value(KEY, "  ") is None and personal.hash_value(KEY, 5) is None
    assert personal.hash_value(KEY, ["user_0001", "", "user_0002"]) == [personal.hmac_hex(KEY, "user_0001"), personal.hmac_hex(KEY, "user_0002")]
    assert personal.hash_value(KEY, []) == []


# ---- own handles -------------------------------------------------------------------------------------------------------

def test_own_handles_come_from_the_record_normalised_and_long_enough():
    record = {"creator": "User_00001", "editors_tags": ["abcdefg", "user_00002", ""], "last_editor": None, "product_name": "not a name field"}
    assert personal.own_handles(record, ["creator", "editors_tags", "last_editor"], 8) == {"user_00001", "user_00002"}


def test_redact_replaces_whole_words_only_case_insensitively():
    h = {"user_00001"}
    for text, expected in (("photo by user_00001.", f"photo by {SENTINEL}."), ("USER_00001 foods", f"{SENTINEL} foods"),
                           ("a (user_00001) b", f"a ({SENTINEL}) b"), ("user_00001, user_00001", f"{SENTINEL}, {SENTINEL}")):
        assert personal.redact_handles(text, h, SENTINEL)[0] == expected, text
    for text in ("byuser_00001", "user_00001x", "xuser_00001y", "user_00001-bakery", "www.user_00001.com"):
        assert personal.redact_handles(text, h, SENTINEL) == (text, 0), text


def test_redact_counts_and_leaves_texts_without_names_alone():
    assert personal.redact_handles("a user_00001 b user_00002", {"user_00001", "user_00002"}, SENTINEL)[1] == 2
    assert personal.redact_handles("Choco Crunch biscuits", {"user_00001"}, SENTINEL) == ("Choco Crunch biscuits", 0)
    assert personal.redact_handles("anything", set(), SENTINEL) == ("anything", 0)
    assert personal.redact_handles("", {"user_00001"}, SENTINEL) == ("", 0)


def test_redact_prefers_the_longest_name():
    out, n = personal.redact_handles("by user_00001_shop", {"user_00001", "user_00001_shop"}, SENTINEL)
    assert out == f"by {SENTINEL}" and n == 1


def test_a_name_with_regex_characters_is_matched_literally():
    assert personal.redact_handles("by a.b+c-d_name", {"a.b+c-d_name"}, SENTINEL) == (f"by {SENTINEL}", 1)


# ---- scrub -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "write to redacted1@example.org", "see www.example.com now", "https://shop.example/page?id=3",
    "instagram.com/some_shop", "facebook.com/some.shop/", "contact @some_shop", "name at gmail dot com",
    "name (at) gmail (dot) com", "aadhaar 2345 6789 0123", "PAN ABCDE1234F here", "GSTIN 27ABCDE1234F1Z5 Mumbai"])
def test_each_pattern_class_is_removed(text):
    cleaned, n = personal.scrub(text, PATTERNS)
    assert n >= 1 and "[removed]" in cleaned and not personal.has_pattern(cleaned, PATTERNS), text


@pytest.mark.parametrize("text", [
    "Choco biscuits 250 g, EAN 8901234567890, 12.5% sugar", "Best before 14.10.2026", "Lot 9876543210", "+91 98765 43210",
    "Order 4256112345678", "pack of 6 x 33 cl", "vitamin B12 2.4 µg"])
def test_barcodes_dates_lot_codes_and_phone_numbers_are_left_alone(text):
    assert personal.scrub(text, PATTERNS) == (text, 0)


def test_a_gstin_is_removed_whole_not_only_its_pan():
    cleaned, n = personal.scrub("27ABCDE1234F1Z5", PATTERNS)
    assert cleaned == "[removed]" and n == 1


def test_scrub_counts_every_substitution():
    assert personal.scrub("a@b.org and www.x.com and @shop_name", PATTERNS)[1] == 3


# ---- fingerprint -------------------------------------------------------------------------------------------------------

def test_fingerprint_ignores_case_spacing_and_width_but_not_content():
    a = personal.fingerprint("Sugar,  Wheat flour\n(gluten), SALT")
    assert a == personal.fingerprint("sugar, wheat flour (gluten), salt") and len(a) == 64 and int(a, 16) >= 0
    assert a != personal.fingerprint("sugar, wheat flour, salt")


def test_fingerprint_is_none_without_text():
    for v in (None, "", "   \n ", 5, ["sugar"]):
        assert personal.fingerprint(v) is None


# ---- quantity and serving size -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("250 g", (250.0, "g", None)), ("250g", (250.0, "g", None)), ("1,5 l", (1.5, "l", None)), ("250 gr", (250.0, "g", None)),
    ("6 x 33 cl", (33.0, "cl", 6)), ("6x50g", (50.0, "g", 6)), ("250 g x 4", (250.0, "g", 4)), ("500 G", (500.0, "g", None)),
    ("250 g (8.8 oz)", (250.0, "g", None)), ("250 g e", (250.0, "g", None)), ("250 g.", (250.0, "g", None)),
    ("250 g / 250 ml", (250.0, "g", None)), ("6 x 50 g = 300 g", (50.0, "g", 6)),
    ("330 мл", (330.0, "ml", None)), ("500 гр", (500.0, "g", None)), ("500 γρ", (500.0, "g", None)),
    ("1 kg", (1.0, "kg", None)), ("12 oz", (12.0, "oz", None))])
def test_quantity_parses_to_amount_unit_multiplier(text, expected):
    assert personal.parse_quantity(text, UNITS) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "kg", "12", "approx 5 kg", "a few", "0 g", "x g", 250, "1000000 g"])
def test_quantity_that_does_not_parse_is_all_none(text):
    assert personal.parse_quantity(text, UNITS) == (None, None, None)


@pytest.mark.parametrize("text, expected", [
    ("30 g", (30.0, "g")), ("1 cup (240 ml)", (240.0, "ml")), ("2 slices (30 g)", (30.0, "g")), ("1/2 cup (120 ml)", (120.0, "ml")),
    ("12,5 g", (12.5, "g")), ("1 serving (30g)", (30.0, "g")), ("1 порция (30 г)", (30.0, "g"))])
def test_serving_takes_the_first_amount_in_grams_or_millilitres(text, expected):
    assert personal.parse_serving(text, UNITS) == expected


@pytest.mark.parametrize("text", [None, "", "1 serving", "1 cup", "g (valeurs nutritionnelles moyennes", "2 oz", 30])
def test_serving_without_a_gram_or_millilitre_amount_is_none(text):
    assert personal.parse_serving(text, UNITS) == (None, None)


# ---- shape checks ------------------------------------------------------------------------------------------------------

SHAPES = personal.compile_shapes(C)


@pytest.mark.parametrize("tag, ok", [
    ("en:milk", True), ("en:Groceries", True), ("fr:café-au-lait", True), ("bg:утвърден-стандарт", True),
    ("fr:Autres produits", False), ("de:Milch und Milchderivate", False), ("fr:\\ origin\\ :[\\ France\\ ]}", False),
    ("en:", False), ("milk", False), ("en:a@b.org", False), ("", False), (None, False), (5, False)])
def test_tag_shape(tag, ok):
    assert personal.shape_ok(tag, SHAPES["tag"]) is ok


@pytest.mark.parametrize("key, ok", [("energy-kj", True), ("vitamin-b12", True), ("sugars", True), ("Energy", False), ("a b", False), ("", False), ("-x", False)])
def test_nutrient_key_shape(key, ok):
    assert personal.shape_ok(key, SHAPES["nutrient_key"]) is ok


@pytest.mark.parametrize("value, ok", [("packaging", True), ("100g", True), ("100mmol/l", True), ("as_sold", True), ("two words", False), ("x" * 21, False)])
def test_enum_shape(value, ok):
    assert personal.shape_ok(value, SHAPES["enum"]) is ok
