"""The legacy-nutriments mapper (contract v3), on real old-format India products from OFF's full dump.

p2_lakehouse/tests/fixtures/seed_india_legacy.jsonl holds real records (sanitised, see bootstrap/extract_seed_fixtures.py):
four India products with real old-format nutrients and two whose only `_100g` keys are OFF's computed ones. Edge cases are made
the way test_transform.py makes them: one field of a real record is changed.
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, run, transform  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
LINEAGE = {"source_file": "seed-dump:2026-10-13:part-0009", "file_sha256": "cd" * 32, "bronze_ingested_at": "2026-10-15T10:00:00",
           "silver_processed_at": "2026-10-15T10:05:00", "job_run_id": "test-run"}
C = contract.load()
CTX = transform.Context(C, KEY)
LEGACY = [json.loads(json.loads(x)["raw_json"]) | {"_case": json.loads(x)["case"]} for x in (FIX / "seed_india_legacy.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
REAL = {d["code"]: d for d in LEGACY if d["_case"] == "india_legacy_nutriments"}
COMPUTED_ONLY = [d for d in LEGACY if d["_case"] == "india_legacy_computed_keys_only"]
A, B, G, H = "9346927008080", "8906067024930", "8906107175929", "8906019402243"


def go(d):
    d = {k: v for k, v in d.items() if k != "_case"}
    return transform.process(json.dumps(d, ensure_ascii=False), CTX, LINEAGE)


def row(code):
    r = go(REAL[code])
    assert r.kind == "silver"
    return r.row


def test_fixtures_are_what_the_tests_assume():
    assert len(REAL) == 4 and len(COMPUTED_ONLY) == 2
    for d in LEGACY:
        assert "en:india" in d["countries_tags"] and not (d.get("nutrition") or {}).get("aggregated_set")


def test_a_real_old_format_product_gets_the_typed_columns_and_the_nutrients_map():
    r = row(A)       # energy_100g 1120 (kJ), energy-kcal_100g 269, fat 19, saturated-fat 13, carbohydrates 2.5, sugars 2.2, proteins 21, salt 0.07, sodium 0.028
    assert r["nutrition_format"] == "legacy"
    assert (r["energy_kj"], r["energy_kcal"], r["fat"], r["saturated_fat"]) == (1120.0, 269.0, 19.0, 13.0)
    assert (r["carbohydrates"], r["sugars"], r["proteins"], r["salt"], r["sodium"]) == (2.5, 2.2, 21.0, 0.07, 0.028)
    assert r["fiber"] is None and r["starch"] is None
    assert r["nutrients"]["fat"] == {"value": 19.0, "unit": "g", "modifier": None}


def test_energy_units_follow_the_key_not_the_unit_the_user_typed():
    raw = REAL[A]["nutriments"]
    assert raw["energy_unit"] == "kcal" and raw["energy_100g"] == 1120      # the old format's own inconsistency
    n = row(A)["nutrients"]
    assert n["energy"] == {"value": 1120.0, "unit": "kJ", "modifier": None}
    assert n["energy-kcal"] == {"value": 269.0, "unit": "kcal", "modifier": None}


def test_small_values_and_minerals_keep_their_numbers_in_grams():
    assert row(B)["nutrients"]["cholesterol"] == {"value": 1.86e-06, "unit": "g", "modifier": None}
    n = row(H)["nutrients"]
    assert n["calcium"] == {"value": 0.0779, "unit": "g", "modifier": None} and n["iron"]["value"] == 0.002
    assert row(H)["fiber"] == 3.3 and "trans-fat" in n


def test_the_basis_columns_say_what_the_old_format_does_not_know():
    for code in REAL:
        r = row(code)
        assert r["nutrition_per"] is None and r["nutrition_preparation"] == "as_sold" and r["input_sets"] is None


def test_only_allowed_nutrient_keys_come_through_and_no_other_old_key_is_read():
    allowed = set(C["legacy_nutriments"]["allowed_keys"])
    for code, d in REAL.items():
        got = set(row(code)["nutrients"])
        assert got <= allowed
        expected = {k[:-5] for k in d["nutriments"] if k.endswith("_100g") and k[:-5] in allowed}
        assert got == expected, code
        assert not any(k.endswith(("_unit", "_value", "_serving", "_computed")) for k in got)


def test_a_product_with_only_computed_keys_is_not_legacy():
    for d in COMPUTED_ONLY:
        r = go(d)
        assert r.kind == "silver" and r.row["nutrition_format"] == "none"
        assert r.row["nutrients"] is None and r.row["energy_kcal"] is None and r.row["nutrition_preparation"] is None


def test_the_new_format_wins_when_a_record_has_both():
    new = json.loads(json.dumps(REAL[A]))
    new["nutrition"] = {"aggregated_set": {"per": "100g", "preparation": "as_sold", "nutrients": {"fat": {"value": 7.5, "unit": "g"}}},
                        "input_sets": []}
    r = go(new).row
    assert r["nutrition_format"] == "new" and r["fat"] == 7.5 and set(r["nutrients"]) == {"fat"}


def test_a_value_that_is_not_a_finite_number_is_skipped_and_counted():
    for bad in ("abc", True, math.nan, math.inf, [1]):
        d = json.loads(json.dumps(REAL[A]))
        d["nutriments"]["fat_100g"] = bad
        r = go(d)
        assert r.kind == "silver" and r.row["fat"] is None and "fat" not in r.row["nutrients"], bad
        assert r.coerce_failures["legacy_nutriments.value"] == 1, bad
        assert r.row["energy_kcal"] == 269.0                       # the rest of the record is unaffected


def test_a_number_written_as_text_is_read_as_a_number():
    d = json.loads(json.dumps(REAL[A]))
    d["nutriments"]["fat_100g"] = "19"
    assert go(d).row["fat"] == 19.0


def test_prepared_and_unknown_keys_are_ignored():
    d = json.loads(json.dumps(REAL[A]))
    d["nutriments"]["fat_prepared_100g"] = 99
    d["nutriments"]["Some Free Text_100g"] = 5
    d["nutriments"]["nova-group_100g"] = 4
    r = go(d)
    assert set(r.row["nutrients"]) == set(row(A)["nutrients"]) and r.row["fat"] == 19.0


def test_a_modifier_is_kept_only_if_it_has_the_allowed_shape():
    d = json.loads(json.dumps(REAL[A]))
    d["nutriments"]["salt_modifier"] = "<"
    assert go(d).row["nutrients"]["salt"]["modifier"] == "<"
    d["nutriments"]["salt_modifier"] = "someone's note"
    r = go(d)
    assert r.row["nutrients"]["salt"]["modifier"] is None and r.enums_nulled == 1


def test_a_broken_record_keeps_only_numeric_allowed_legacy_keys_in_its_quarantine_payload():
    d = json.loads(json.dumps(REAL[A]))
    d["code"] = ""
    d["nutriments"]["fat_100g"] = "text"
    r = go(d)
    assert r.kind == "quarantine" and r.reason == "Q_BAD_CODE"
    kept = json.loads(r.payload)["nutriments"]
    assert kept["energy-kcal_100g"] == 269 and "fat_100g" not in kept
    assert not any(k.endswith(("_unit", "_value", "_serving", "_computed")) for k in kept)


def test_a_batch_counts_the_formats():
    rows = [{"code": d["code"], "last_modified_t": d["last_modified_t"], "raw_json": json.dumps({k: v for k, v in d.items() if k != "_case"}),
             "source_file": LINEAGE["source_file"], "file_sha256": LINEAGE["file_sha256"], "ingested_at": datetime(2026, 10, 15, 10, 0)}
            for d in LEGACY]
    res = run.process_batch(rows, CTX, "test-run", datetime(2026, 10, 15, 10, 5))
    assert res.balanced() and res.nutrition_format == {"legacy": 4, "none": 2}
