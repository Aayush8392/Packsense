"""The silver contract (version 3): structure and the guarantees the rest of the code relies on."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract  # noqa: E402

C = contract.load()


def cols():
    return {x["name"]: x for x in C["columns"]}


def test_loads_and_validates_as_version_3():
    assert C["version"] == 3 and len(C["columns"]) == 71 and C["grain"] == ["code", "last_modified_t"]


def test_version_2_is_refused():
    c = copy.deepcopy(C)
    c["version"] = 2
    with pytest.raises(ValueError, match="version 3"):
        contract.validate(c)


def test_key_columns_are_not_nullable():
    assert cols()["code"]["nullable"] is False and cols()["last_modified_t"]["nullable"] is False


def test_dropped_fields_have_no_column():
    for dropped in ("images", "nutriments", "last_modified_by", "data_quality_tags", "owner_fields", "generic_name",
                    "ingredients_text", "quantity", "serving_size"):
        assert dropped not in cols()


def test_free_text_is_down_to_product_name_and_brands():
    free = [x["name"] for x in C["columns"] if x["class"] == "public" and x["type"] == "string" and x.get("scrub")]
    assert free == ["product_name", "brands"]
    assert contract.scrubbed_columns(C) == ["product_name", "brands"]


def test_quantity_serving_and_ingredients_are_structure_not_text():
    c = cols()
    for name, typ in (("quantity_amount", "double"), ("quantity_unit", "string"), ("quantity_multiplier", "int"),
                      ("serving_amount", "double"), ("serving_unit", "string"), ("ingredients_sha256", "string")):
        assert c[name]["type"] == typ and not c[name].get("scrub")


def test_every_identity_column_is_hashed_and_never_leaves_silver():
    personal = set(C["personal_source_fields"])
    for x in C["columns"]:
        if x["from"].replace("$.", "") in personal:
            assert x["class"] == "hashed" and x["name"].endswith("_hmac") and x["egress"] == "never", x["name"]
    assert cols()["hmac_key_version"]["egress"] == "never"


def test_own_handle_redaction_is_for_product_name_and_not_for_brands():
    own = C["own_handle_redaction"]
    assert own["columns"] == ["product_name"] and own["min_length"] == 8 and own["sentinel"] == "‹user›"


def test_validate_refuses_brands_in_own_handle_redaction():
    c = copy.deepcopy(C)
    c["own_handle_redaction"]["columns"] = ["product_name", "brands"]
    with pytest.raises(ValueError, match="brands"):
        contract.validate(c)


def test_quarantine_is_for_broken_records_only():
    assert set(C["quarantine_codes"]) == {"Q_BAD_JSON", "Q_NOT_OBJECT", "Q_BAD_CODE", "Q_BAD_LAST_MODIFIED", "Q_TRANSFORM_ERROR"}
    c = copy.deepcopy(C)
    c["quarantine_codes"]["Q_PII_FOUND"] = "x"
    with pytest.raises(ValueError, match="broken records only"):
        contract.validate(c)


def test_all_scrub_patterns_and_shapes_are_present():
    assert set(contract.SCRUB_PATTERNS) <= set(C["scrub"]) and set(contract.SHAPES) <= set(C["shape"])


def test_units_cover_latin_cyrillic_and_greek_spellings():
    units = C["parsing"]["units"]
    for u in ("g", "gr", "kg", "ml", "cl", "l", "oz", "г", "гр", "мл", "л", "γρ"):
        assert u in units


def test_egress_settings():
    assert C["egress"] == {"handle_min_length": 8, "ordinary_word_min_products": 10, "refuse_on_residue": True}


def test_validate_rejects_a_duplicate_column_a_bad_class_and_a_bad_type():
    c = copy.deepcopy(C)
    c["columns"].append(copy.deepcopy(c["columns"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        contract.validate(c)
    c = copy.deepcopy(C)
    c["columns"][0]["class"] = "secret"
    with pytest.raises(ValueError, match="class"):
        contract.validate(c)
    c = copy.deepcopy(C)
    c["columns"][0]["type"] = "varchar"
    with pytest.raises(ValueError, match="type"):
        contract.validate(c)


def test_validate_rejects_a_hashed_column_that_reads_a_non_personal_field_or_can_leave():
    c = copy.deepcopy(C)
    col = next(x for x in c["columns"] if x["class"] == "hashed")
    col["from"] = "$.product_name"
    with pytest.raises(ValueError, match="personal_source_fields"):
        contract.validate(c)
    c = copy.deepcopy(C)
    del next(x for x in c["columns"] if x["class"] == "hashed")["egress"]
    with pytest.raises(ValueError, match="egress"):
        contract.validate(c)


def test_relocate_moves_the_tables_and_leaves_the_original():
    moved = contract.relocate(C, silver_schema="workspace.scratch_s", bronze_schema="workspace.scratch_b")
    assert moved["table"] == "workspace.scratch_s.silver_product_versions" and moved["source_table"] == "workspace.scratch_b.bronze_delta_raw"
    assert C["table"] == "workspace.packsense_silver.silver_product_versions"


# ---- legacy nutriments (version 3) -----------------------------------------------------------------------------------

def test_legacy_section_is_complete_and_consistent():
    leg = C["legacy_nutriments"]
    assert leg["suffix"] == "_100g" and leg["default_unit"] == "g"
    assert len(leg["allowed_keys"]) == len(set(leg["allowed_keys"])) > 100
    assert set(leg["units"]) <= set(leg["allowed_keys"])
    assert leg["units"]["energy"] == "kJ" and leg["units"]["energy-kcal"] == "kcal" and leg["units"]["alcohol"] == "% vol"


def test_computed_keys_are_not_allowed_as_legacy_nutrients():
    allowed = set(C["legacy_nutriments"]["allowed_keys"])
    for computed in ("nova-group", "nutrition-score-fr", "fruits-vegetables-nuts", "fruits-vegetables-legumes", "ph",
                     "glycemic-index", "water-hardness", "carbon-footprint", "fruits-vegetables-nuts-estimate-from-ingredients"):
        assert computed not in allowed


def test_a_legacy_key_that_breaks_the_nutrient_shape_is_refused():
    c = copy.deepcopy(C)
    c["legacy_nutriments"]["allowed_keys"].append("Free Text")
    with pytest.raises(ValueError, match="nutrient_key"):
        contract.validate(c)


def test_a_duplicate_legacy_key_and_a_unit_for_an_unlisted_key_are_refused():
    c = copy.deepcopy(C)
    c["legacy_nutriments"]["allowed_keys"].append("fat")
    with pytest.raises(ValueError, match="duplicates"):
        contract.validate(c)
    c = copy.deepcopy(C)
    c["legacy_nutriments"]["units"]["not-a-listed-key"] = "g"
    with pytest.raises(ValueError, match="not allowed"):
        contract.validate(c)
