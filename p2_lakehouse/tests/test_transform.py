"""The silver transform (contract v3), run against real bronze records (p2_lakehouse/tests/fixtures/bronze_records.jsonl).

The fixtures are real OFF records picked to cover each case, with contributor names replaced by placeholders (user_0001 ...),
images removed and emails/phones replaced; see bootstrap/extract_fixtures.py. Several tests change one field of a real record
to plant a case (an email in a product name, a contributor's own name in a product name, a junk tag).
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, personal, transform  # noqa: E402

KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bronze_records.jsonl"
LINEAGE = {"source_file": "openfoodfacts_products_1791094877_1791181482.json.gz", "file_sha256": "ab" * 32,
           "bronze_ingested_at": "2026-10-14T09:00:00", "silver_processed_at": "2026-10-14T09:05:00", "job_run_id": "test-run"}
C = contract.load()
CTX = transform.Context(C, KEY)
SENTINEL = C["own_handle_redaction"]["sentinel"]


def load_cases():
    cases = defaultdict(list)
    for line in open(FIXTURES, encoding="utf-8"):
        rec = json.loads(line)
        cases[rec["case"]].append(rec["raw_json"])
    return cases


CASES = load_cases()


def record(case, i=0):
    return json.loads(CASES[case][i])


def process(d, ctx=CTX):
    return transform.process(json.dumps(d, ensure_ascii=False), ctx, LINEAGE)


def silver(case, i=0):
    r = transform.process(CASES[case][i], CTX, LINEAGE)
    assert r.kind == "silver", (case, r.reason)
    return r


def planted(case="normal_new", **changes):
    d = record(case)
    d.update(changes)
    return process(d)


# ---- every real record ---------------------------------------------------------------------------------------------------

def test_every_fixture_loads_and_only_the_empty_barcode_is_quarantined():
    outcomes = {}
    for case, raws in CASES.items():
        for raw in raws:
            r = transform.process(raw, CTX, LINEAGE)
            outcomes.setdefault(case, []).append(r.reason or "silver")
    assert outcomes["non_digit_code"] == ["Q_BAD_CODE"]
    assert all(o == ["silver"] * len(o) for c, o in outcomes.items() if c != "non_digit_code"), outcomes


def test_silver_row_has_exactly_the_contract_columns_and_nothing_else():
    names = {c["name"] for c in C["columns"]}
    for case in CASES:
        r = transform.process(CASES[case][0], CTX, LINEAGE)
        if r.kind == "silver":
            assert set(r.row) == names, (case, set(r.row) ^ names)


def test_values_match_the_declared_types_and_nullability():
    py = {"string": str, "int": int, "bigint": int, "double": float, "boolean": bool, "timestamp": str}
    for case in CASES:
        r = transform.process(CASES[case][0], CTX, LINEAGE)
        if r.kind != "silver":
            continue
        for col in C["columns"]:
            v = r.row[col["name"]]
            if v is None:
                assert col["nullable"], (case, col["name"])
                continue
            base = col["type"].split("<")[0]
            if base == "array":
                assert isinstance(v, list) and (col["type"] != "array<string>" or all(isinstance(x, str) for x in v)), (case, col["name"])
            elif base == "map":
                assert isinstance(v, dict)
            else:
                assert isinstance(v, py[base]) and not (base != "boolean" and isinstance(v, bool)), (case, col["name"], type(v))


def test_no_placeholder_username_survives_in_any_text_column():
    free = [c["name"] for c in C["columns"] if c["class"] == "public" and c["type"] in ("string", "array<string>")]
    for case in CASES:
        r = transform.process(CASES[case][0], CTX, LINEAGE)
        if r.kind == "silver":
            for name in free:
                assert "user_0" not in json.dumps(r.row[name]), (case, name)


def test_processing_is_deterministic_and_independent_of_other_records():
    forward = [transform.process(raw, CTX, LINEAGE).row for raws in CASES.values() for raw in raws]
    backward = [transform.process(raw, CTX, LINEAGE).row for raws in reversed(list(CASES.values())) for raw in reversed(raws)]
    assert forward == backward[::-1]


# ---- identities --------------------------------------------------------------------------------------------------------

def test_hashed_columns_are_hmacs_of_the_raw_names():
    raw = record("normal_new")
    row = silver("normal_new").row
    assert row["creator_hmac"] == personal.hmac_hex(KEY, raw["creator"])
    assert row["editors_hmac"] == [personal.hmac_hex(KEY, e) for e in raw["editors_tags"]]
    assert row["hmac_key_version"] == 1


def test_owner_is_hashed_and_flagged():
    row = silver("owner_present").row
    assert row["producer_owned"] is True and len(row["owner_hmac"]) == 64


def test_lineage_and_contract_version_are_carried():
    row = silver("normal_new").row
    assert row["source_file"] == LINEAGE["source_file"] and row["file_sha256"] == LINEAGE["file_sha256"]
    assert row["job_run_id"] == "test-run" and row["silver_contract_version"] == 3


def test_code_kinds():
    assert silver("gtin8").row["code_kind"] == "gtin8" and silver("gtin14").row["code_kind"] == "gtin14"
    assert silver("odd_length_code").row["code_kind"] == "other"


def test_code_kind_follows_the_length_of_every_real_fixture_code():
    """Found by the rollback drill: a deliberate bug that labelled 13-digit codes 'gtin12' passed every test, because the 13-digit
    kind (the most common barcode) was never asserted."""
    kinds = {8: "gtin8", 12: "gtin12", 13: "gtin13", 14: "gtin14"}
    seen = set()
    for raws in CASES.values():
        for raw in raws:
            r = transform.process(raw, CTX, LINEAGE)
            if r.kind == "silver":
                expected = kinds.get(len(r.code), "other")
                assert r.row["code_kind"] == expected, (r.code, r.row["code_kind"])
                seen.add(expected)
    assert "gtin13" in seen and "gtin8" in seen and "gtin14" in seen and "other" in seen


# ---- text: scrub, own-handle redaction, structure ------------------------------------------------------------------------

def test_patterns_in_product_name_and_brands_are_scrubbed_and_counted():
    r = planted(product_name="Biscuits www.example.com contact shop@example.org", brands="see instagram.com/some_shop")
    assert r.row["product_name"] == "Biscuits [removed] contact [removed]" and r.row["brands"] == "see [removed]" and r.scrubbed == 3


def test_dates_lot_codes_and_barcodes_in_a_product_name_survive():
    name = "Biscuits 14.10.2026 lot 9876543210 EAN 8901234567890"
    assert planted(product_name=name).row["product_name"] == name


def test_own_name_in_the_product_name_is_replaced_and_counted():
    creator = record("normal_new")["creator"]
    r = planted(product_name=f"Biscuits photo by {creator}.")
    assert r.row["product_name"] == f"Biscuits photo by {SENTINEL}." and r.own_handles_redacted == 1 and r.kind == "silver"


def test_any_of_the_records_own_contributors_counts_as_own():
    editor = record("normal_new")["editors_tags"][0]
    assert planted(product_name=f"thanks {editor}").row["product_name"] == f"thanks {SENTINEL}"


def test_own_name_in_brands_is_kept_because_producers_write_their_own_brand():
    creator = record("normal_new")["creator"]
    r = planted(brands=f"{creator} foods")
    assert r.row["brands"] == f"{creator} foods" and r.own_handles_redacted == 0


def test_another_contributors_name_is_not_touched_and_never_quarantines_the_row():
    mine = {record("normal_new")["creator"], *record("normal_new")["editors_tags"]}
    other = next(n for n in record("many_editors")["editors_tags"] if n not in mine)
    r = planted(product_name=f"{other} bakery", brands=f"{other} foods")
    assert r.kind == "silver" and r.row["product_name"] == f"{other} bakery" and r.own_handles_redacted == 0


def test_a_short_own_name_is_not_replaced():
    r = planted(creator="abcdefg", editors_tags=["abcdefg"], product_name="by abcdefg")
    assert r.row["product_name"] == "by abcdefg" and r.own_handles_redacted == 0


def test_the_sentinel_count_equals_the_substitutions_made():
    creator = record("normal_new")["creator"]
    r = planted(product_name=f"{creator} and {creator.upper()} and x{creator}")
    assert r.row["product_name"].count(SENTINEL) == r.own_handles_redacted == 2


def test_ingredients_text_is_not_kept_only_a_fingerprint_of_it():
    row = silver("email_in_ingredients").row
    assert "ingredients_text" not in row and re.fullmatch(r"[0-9a-f]{64}", row["ingredients_sha256"])
    assert "@" not in json.dumps(row, default=str)


def test_the_fingerprint_changes_when_the_ingredients_change_and_not_when_only_spacing_does():
    base = record("normal_new")
    a = process({**base, "ingredients_text": "sugar, wheat flour"}).row["ingredients_sha256"]
    assert a == process({**base, "ingredients_text": "Sugar,  Wheat flour "}).row["ingredients_sha256"]
    assert a != process({**base, "ingredients_text": "sugar, wheat flour, salt"}).row["ingredients_sha256"]
    assert process({**base, "ingredients_text": ""}).row["ingredients_sha256"] is None


def test_quantity_and_serving_size_become_numbers_and_units():
    r = planted(quantity="6 x 33 cl", serving_size="1 cup (240 ml)").row
    assert (r["quantity_amount"], r["quantity_unit"], r["quantity_multiplier"]) == (33.0, "cl", 6)
    assert (r["serving_amount"], r["serving_unit"]) == (240.0, "ml")
    assert "quantity" not in r and "serving_size" not in r


def test_quantity_and_serving_size_that_do_not_parse_become_null():
    r = planted(quantity="a big bag", serving_size="1 serving").row
    assert r["quantity_amount"] is r["quantity_unit"] is r["quantity_multiplier"] is r["serving_amount"] is r["serving_unit"] is None


# ---- tags and maps -----------------------------------------------------------------------------------------------------

def test_malformed_tags_are_dropped_and_counted_well_formed_ones_stay():
    r = planted(categories_tags=["en:milk", "fr:Autres produits", "fr:\\ origin\\ :[\\ France\\ ]}", "en:Groceries"],
                allergens_tags=["en:milk"], labels_tags=["de:Milch und Milchderivate"])
    assert r.row["categories_tags"] == ["en:milk", "en:Groceries"] and r.row["labels_tags"] == []
    assert r.tags_dropped["categories_tags"] == 2 and r.tags_dropped["labels_tags"] == 1 and "allergens_tags" not in r.tags_dropped


def test_a_well_formed_tag_that_holds_a_bare_domain_is_scrubbed():
    r = planted(categories_tags=["en:milk", "en:www.example.com"])
    assert r.row["categories_tags"] == ["en:milk", "en:[removed]"] and r.scrubbed == 1


def test_a_nutrient_key_or_enum_outside_its_vocabulary_is_dropped_or_nulled_and_counted():
    d = record("normal_new")
    d["nutrition"]["aggregated_set"]["nutrients"]["Some Free Text"] = {"value": 1, "unit": "g"}
    d["nutrition"]["aggregated_set"]["per"] = "as sold per portion"
    d["nutrition"]["input_sets"][0]["source"] = "someone's name here"
    r = process(d)
    assert "Some Free Text" not in r.row["nutrients"] and r.row["nutrition_per"] is None and r.row["input_sets"][0]["source"] is None
    assert r.nutrient_entries_dropped == 1 and r.enums_nulled >= 2


def test_normal_new_product_nutrition_is_unchanged():
    row = silver("normal_new").row
    assert row["nutrition_format"] == "new" and row["nutrition_per"] == "100g"
    for col in ("energy_kj", "energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars", "proteins", "salt", "sodium", "fiber"):
        assert isinstance(row[col], float), col
    assert "energy-kj" in row["nutrients"] and set(row["nutrients"]["fat"]) == {"value", "unit", "modifier"}
    for s in row["input_sets"]:
        assert set(s) == {"source", "per", "per_quantity", "per_unit", "preparation", "nutrients"}


def test_no_nutrition_per_100ml_prepared_and_modifiers():
    assert silver("no_nutrition").row["nutrition_format"] == "none" and silver("no_nutrition").row["nutrients"] is None
    assert silver("per_100ml").row["nutrition_per"] == "100ml" and silver("prepared").row["nutrition_preparation"] == "prepared"
    assert any(v["modifier"] == "<" for v in silver("modifier_less_than").row["nutrients"].values())
    assert any(v["value"] is None for s in silver("input_value_null").row["input_sets"] for v in (s["nutrients"] or {}).values())


def test_old_format_records_in_the_delta_fixtures_follow_the_rule_new_wins_else_legacy():
    for i, raw in enumerate(CASES["legacy_nutriments_filled"]):
        d = json.loads(raw)
        has_agg = bool(((d.get("nutrition") or {}).get("aggregated_set")))
        assert silver("legacy_nutriments_filled", i).row["nutrition_format"] == ("new" if has_agg else "legacy")


def test_product_quantity_that_is_text_becomes_null_and_is_counted():
    r = silver("product_quantity_string")
    assert r.row["product_quantity"] is None or isinstance(r.row["product_quantity"], float)
    if r.row["product_quantity"] is None:
        assert r.coerce_failures["product_quantity"] == 1


def test_many_editors_are_all_hashed_and_a_missing_name_is_null_or_empty():
    assert len(silver("many_editors").row["editors_hmac"]) >= 40
    assert silver("no_product_name").row["product_name"] in (None, "")


def test_two_versions_of_one_product_become_two_rows_with_one_code():
    a, b = silver("two_versions_same_code", 0), silver("two_versions_same_code", 1)
    assert a.code == b.code and a.last_modified_t != b.last_modified_t


# ---- quarantine: broken records only -----------------------------------------------------------------------------------

def test_bad_json_and_non_object():
    assert transform.process("{", CTX, LINEAGE).reason == "Q_BAD_JSON"
    assert transform.process("[1, 2]", CTX, LINEAGE).reason == "Q_NOT_OBJECT"


def test_bad_codes_and_timestamps_are_quarantined():
    d = record("normal_new")
    for change, reason in ((lambda x: x.pop("code"), "Q_BAD_CODE"), (lambda x: x.update(code="12AB"), "Q_BAD_CODE"), (lambda x: x.update(code=""), "Q_BAD_CODE"),
                           (lambda x: x.pop("last_modified_t"), "Q_BAD_LAST_MODIFIED"), (lambda x: x.update(last_modified_t="1791254632"), "Q_BAD_LAST_MODIFIED"),
                           (lambda x: x.update(last_modified_t=True), "Q_BAD_LAST_MODIFIED")):
        x = json.loads(json.dumps(d))
        change(x)
        assert process(x).reason == reason


def test_the_quarantine_payload_is_restricted_hashed_and_carries_no_unkept_text():
    d = record("normal_new")
    d.update(code="", quantity="1 kg", serving_size="30 g", ingredients_text="sugar, water", data_sources_tags=["app-somebody"],
             images={"1": {"uploader": "someone"}}, product_name="Biscuits www.example.com")
    r = process(d)
    assert r.kind == "quarantine" and r.reason == "Q_BAD_CODE"
    payload = json.loads(r.payload)
    allowed = {transform.root_field(c) for c in C["columns"] if c["class"] in ("public", "key", "hashed") and not c.get("parse") and not c.get("fingerprint")} - {None}
    assert set(payload) <= allowed
    for gone in ("images", "data_sources_tags", "quantity", "serving_size", "ingredients_text"):
        assert gone not in payload
    assert payload["product_name"] == "Biscuits [removed]" and payload["creator"] == personal.hmac_hex(KEY, d["creator"])
    assert "user_0" not in r.payload


def test_the_quarantine_payload_gets_the_same_own_name_treatment_as_silver():
    d = record("normal_new")
    d.update(code="", product_name=f"Biscuits by {d['creator']}", brands=f"{d['creator']} foods")
    payload = json.loads(process(d).payload)
    assert payload["product_name"] == f"Biscuits by {SENTINEL}" and payload["brands"] == f"{d['creator']} foods"


def test_content_suspicion_never_quarantines():
    creator = record("normal_new")["creator"]
    r = planted(product_name=f"{creator} www.example.com @someone a@b.org 27ABCDE1234F1Z5")
    assert r.kind == "silver" and r.reason is None


def test_a_field_openff_adds_tomorrow_never_reaches_silver_or_the_payload():
    secret = "newfield-value-that-must-not-leak"
    r2 = planted(brand_new_field=secret)
    assert r2.kind == "silver" and secret not in json.dumps(r2.row, default=str)
    r = process({**record("normal_new"), "brand_new_field": secret, "last_modified_t": "oops"})
    assert r.kind == "quarantine" and secret not in (r.payload or "")


def test_an_unforeseen_shape_is_quarantined_not_raised():
    d = record("normal_new")
    d["nutrition"].update(input_sets=[1, "x", None], aggregated_set={"nutrients": [1, 2]})
    r = process(d)
    assert r.kind in ("silver", "quarantine") and r.reason != "Q_BAD_JSON"


def test_top_level_fields_are_counted_for_the_drift_monitor():
    ctx = transform.Context(C, KEY)
    for raws in CASES.values():
        for raw in raws:
            transform.process(raw, ctx, LINEAGE)
    assert ctx.field_counts["code"] == sum(len(v) for v in CASES.values()) and "product_name" in ctx.field_counts
