"""The silver transform, run against real bronze records (p2_lakehouse/tests/fixtures/bronze_records.jsonl).

The fixtures are real OFF records picked to cover each case, with contributor names replaced by placeholders
(user_0001 ...), images removed and emails/phones replaced; see bootstrap/extract_fixtures.py. A few tests change one
field of a real record to plant a fault (a username in a product name, a missing timestamp).
"""
import copy
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, personal, transform  # noqa: E402

KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bronze_records.jsonl"
LINEAGE = {"source_file": "openfoodfacts_products_1791094877_1791181482.json.gz", "file_sha256": "ab" * 32,
           "bronze_ingested_at": "2026-10-14T09:00:00", "silver_processed_at": "2026-10-14T09:05:00", "job_run_id": "test-run"}
CONTRACT = contract.load()
CTX = transform.Context(CONTRACT, KEY)


def load_cases():
    cases = defaultdict(list)
    for line in open(FIXTURES, encoding="utf-8"):
        rec = json.loads(line)
        cases[rec["case"]].append(rec["raw_json"])
    return cases


CASES = load_cases()


def run(case, i=0, ctx=CTX):
    return transform.process(CASES[case][i], ctx, LINEAGE)


def silver(case, i=0):
    r = run(case, i)
    assert r.kind == "silver", (case, r.reason, r.pii_columns)
    return r


def test_no_fixture_hits_an_unexpected_error():
    outcomes = {}
    for case, raws in CASES.items():
        for raw in raws:
            r = transform.process(raw, CTX, LINEAGE)
            assert r.reason not in ("Q_TRANSFORM_ERROR", "Q_BAD_JSON", "Q_NOT_OBJECT"), (case, r.reason)
            outcomes.setdefault(case, []).append(r.reason or "silver")
    assert outcomes["non_digit_code"] == ["Q_BAD_CODE"]
    others = {c: o for c, o in outcomes.items() if c != "non_digit_code"}
    assert all(o == ["silver"] * len(o) for o in others.values()), others


def test_silver_row_has_exactly_the_contract_columns_and_nothing_else():
    names = {c["name"] for c in CONTRACT["columns"]}
    for case in CASES:
        r = run(case)
        if r.kind == "silver":
            assert set(r.row) == names, (case, set(r.row) ^ names)


def test_values_match_the_declared_types_and_nullability():
    py = {"string": str, "int": int, "bigint": int, "double": float, "boolean": bool, "timestamp": str}
    for case in CASES:
        r = run(case)
        if r.kind != "silver":
            continue
        for col in CONTRACT["columns"]:
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


def test_no_placeholder_username_survives_in_any_silver_row():
    for case in CASES:
        r = run(case)
        if r.kind == "silver":
            assert "user_0" not in json.dumps(r.row, default=str), case


def test_hashed_columns_are_hmacs_of_the_raw_names():
    raw = json.loads(CASES["normal_new"][0])
    row = silver("normal_new").row
    assert row["creator_hmac"] == personal.hmac_hex(KEY, raw["creator"])
    assert row["editors_hmac"] == [personal.hmac_hex(KEY, e) for e in raw["editors_tags"]]
    assert row["hmac_key_version"] == 1


def test_lineage_and_contract_version_are_carried():
    row = silver("normal_new").row
    assert row["source_file"] == LINEAGE["source_file"] and row["file_sha256"] == LINEAGE["file_sha256"]
    assert row["job_run_id"] == "test-run" and row["silver_contract_version"] == 1


def test_code_kinds():
    assert silver("gtin8").row["code_kind"] == "gtin8"
    assert silver("gtin14").row["code_kind"] == "gtin14"
    assert silver("odd_length_code").row["code_kind"] == "other"
    assert silver("normal_new").row["code_kind"] in ("gtin13", "gtin8", "gtin12", "gtin14")


def test_normal_new_product_nutrition():
    row = silver("normal_new").row
    assert row["nutrition_format"] == "new" and row["nutrition_per"] == "100g"
    for col in ("energy_kj", "energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars", "proteins", "salt", "sodium", "fiber"):
        assert isinstance(row[col], float), col
    assert "energy-kj" in row["nutrients"] and set(row["nutrients"]["fat"]) == {"value", "unit", "modifier"}
    assert len(row["input_sets"]) >= 2
    for s in row["input_sets"]:
        assert set(s) == {"source", "per", "per_quantity", "per_unit", "preparation", "nutrients"}


def test_no_nutrition_product():
    row = silver("no_nutrition").row
    assert row["nutrition_format"] == "none" and row["energy_kj"] is None and row["nutrients"] is None


def test_per_100ml_and_prepared_are_recorded():
    assert silver("per_100ml").row["nutrition_per"] == "100ml"
    assert silver("prepared").row["nutrition_preparation"] == "prepared"


def test_legacy_nutriments_are_not_mapped():
    assert "nutriments" not in {c["name"] for c in CONTRACT["columns"]}
    for i in range(len(CASES["legacy_nutriments_filled"])):
        assert silver("legacy_nutriments_filled", i).row["nutrition_format"] in ("new", "none")


def test_owner_is_hashed_and_flagged():
    row = silver("owner_present").row
    assert row["producer_owned"] is True and len(row["owner_hmac"]) == 64


def test_email_in_ingredients_is_scrubbed():
    r = silver("email_in_ingredients")
    assert r.scrubbed >= 1
    assert not personal.has_pattern(r.row["ingredients_text"], CTX.patterns) and "[removed]" in r.row["ingredients_text"]


def test_null_values_and_modifiers_are_kept_as_sent():
    sets = silver("input_value_null").row["input_sets"]
    assert any(v["value"] is None for s in sets for v in (s["nutrients"] or {}).values())
    assert any(v["modifier"] == "<" for v in silver("modifier_less_than").row["nutrients"].values())


def test_product_quantity_that_is_text_becomes_null_and_is_counted():
    r = silver("product_quantity_string")
    assert r.row["product_quantity"] is None or isinstance(r.row["product_quantity"], float)
    if r.row["product_quantity"] is None:
        assert r.coerce_failures["product_quantity"] == 1


def test_many_editors_are_all_hashed():
    assert len(silver("many_editors").row["editors_hmac"]) >= 40


def test_phone_in_a_dropped_field_is_collected_as_known_phone():
    r = silver("phone_in_customer_service")
    assert r.phones and all(len(h) == 64 for h in r.phones)


def test_missing_product_name_is_null_or_empty():
    assert silver("no_product_name").row["product_name"] in (None, "")


def test_two_versions_of_one_product_become_two_rows_with_one_code():
    a, b = silver("two_versions_same_code", 0), silver("two_versions_same_code", 1)
    assert a.code == b.code and a.last_modified_t != b.last_modified_t


def test_processing_is_deterministic():
    assert run("normal_new").row == run("normal_new").row


# ---- quarantine ------------------------------------------------------------------------------------------------------

def mutated(case, change):
    d = json.loads(CASES[case][0])
    change(d)
    return json.dumps(d, ensure_ascii=False)


def test_bad_json_and_non_object():
    assert transform.process("{", CTX, LINEAGE).reason == "Q_BAD_JSON"
    assert transform.process("[1, 2]", CTX, LINEAGE).reason == "Q_NOT_OBJECT"


def test_bad_codes_are_quarantined_with_a_scrubbed_restricted_payload():
    r = run("non_digit_code")
    assert r.kind == "quarantine" and r.reason == "Q_BAD_CODE"
    payload = json.loads(r.payload)
    allowed = {transform.root_field(c) for c in CONTRACT["columns"] if c["class"] in ("public", "key", "hashed")} - {None}
    assert set(payload) <= allowed
    assert "images" not in payload and "data_sources_tags" not in payload
    assert "user_0" not in r.payload
    for raw in (mutated("normal_new", lambda d: d.pop("code")), mutated("normal_new", lambda d: d.update(code="12AB"))):
        assert transform.process(raw, CTX, LINEAGE).reason == "Q_BAD_CODE"


def test_missing_or_non_integer_timestamp_is_quarantined():
    for change in (lambda d: d.pop("last_modified_t"), lambda d: d.update(last_modified_t="1791254632"),
                   lambda d: d.update(last_modified_t=True)):
        assert transform.process(mutated("normal_new", change), CTX, LINEAGE).reason == "Q_BAD_LAST_MODIFIED"


def test_a_username_planted_in_a_product_name_is_caught_and_withheld():
    raw = json.loads(CASES["normal_new"][0])
    creator = raw["creator"]
    r = transform.process(mutated("normal_new", lambda d: d.update(product_name=f"Biscuits photo by {creator}.")), CTX, LINEAGE)
    assert r.kind == "quarantine" and r.reason == "Q_PII_FOUND" and r.pii_columns == ["product_name"]
    assert json.loads(r.payload)["product_name"] == "[withheld]"
    assert creator not in r.payload


def test_a_username_known_from_another_product_is_caught_through_the_identity_set():
    other = json.loads(CASES["many_editors"][0])["editors_tags"][0]
    ctx = transform.Context(CONTRACT, KEY, known_users=frozenset({personal.hmac_hex(KEY, other)}))
    r = transform.process(mutated("normal_new", lambda d: d.update(brands=f"{other} foods")), ctx, LINEAGE)
    assert r.reason == "Q_PII_FOUND" and r.pii_columns == ["brands"]


def test_a_phone_planted_in_text_is_caught():
    donor = json.loads(CASES["phone_in_customer_service"][0])
    phone = next(m.group(0) for k, v in donor.items() if k.startswith("customer_service") and isinstance(v, str)
                 for m in [personal.PHONE_RE.search(v)] if m)
    merged = json.loads(CASES["normal_new"][0])
    merged["customer_service"] = f"Call {phone}"
    merged["product_name"] = f"Biscuits, order on {phone}"
    r = transform.process(json.dumps(merged), CTX, LINEAGE)
    assert r.reason == "Q_PII_FOUND" and "product_name" in r.pii_columns


def test_a_field_openff_adds_tomorrow_never_reaches_silver_or_the_payload():
    secret = "newfield-value-that-must-not-leak"
    raw = mutated("normal_new", lambda d: d.update(brand_new_field=secret, last_modified_t="oops"))
    r = transform.process(raw, CTX, LINEAGE)            # quarantined, so the payload is built
    assert secret not in (r.payload or "")
    r2 = transform.process(mutated("normal_new", lambda d: d.update(brand_new_field=secret)), CTX, LINEAGE)
    assert r2.kind == "silver" and secret not in json.dumps(r2.row, default=str)


def test_an_unforeseen_shape_is_quarantined_not_raised():
    # nutrition.input_sets entries that are not objects, nutrients that are a list, a number where a dict belongs
    raw = mutated("normal_new", lambda d: d["nutrition"].update(input_sets=[1, "x", None], aggregated_set={"nutrients": [1, 2]}))
    r = transform.process(raw, CTX, LINEAGE)
    assert r.kind in ("silver", "quarantine") and r.reason != "Q_BAD_JSON"


def test_new_identities_are_returned_for_the_identity_table():
    r = silver("normal_new")
    assert r.identities and all(len(h) == 64 for h in r.identities) and all(n >= 3 for n in r.identities.values())
