"""Tests for the data classification (P5 step 5): the file is sound, the generated DATA_CLASSIFICATION.md is current, every silver column has
a class, hashed columns are personal AND masked, gold holds no personal column, and a planted mistake is found."""
import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / "p5_governance"
sys.path.insert(0, str(P5))
sys.path.insert(0, str(ROOT / "p4_modelling"))
import classification_lib as cl  # noqa: E402

SPEC = cl.load_spec()
TABLES = cl.table_columns()
GOLD = cl.gold_columns()


def test_the_classification_file_validates_and_is_sound():
    assert cl.problems(SPEC, TABLES, GOLD) == []


def test_the_generated_document_is_current():
    have = cl.DOC_PATH.read_text(encoding="utf-8")
    assert have == cl.render(SPEC, TABLES, GOLD), "DATA_CLASSIFICATION.md is stale: python p5_governance/bootstrap/render_classification.py"


def test_every_silver_column_is_classified_exactly_once_and_with_a_known_class():
    sc = yaml.safe_load((ROOT / "p2_lakehouse" / "contracts" / "silver.yml").read_text(encoding="utf-8"))
    rows = cl.silver_rows(SPEC)
    assert [r["column"] for r in rows] == [c["name"] for c in sc["columns"]]
    assert {r["class"] for r in rows} <= set(cl.CLASSES)


def test_hashed_columns_are_personal_and_the_key_version_is_internal():
    by = {r["column"]: r for r in cl.silver_rows(SPEC)}
    hashed = [c for c, r in by.items() if r["contract_class"] == "hashed"]
    assert len(hashed) == 10 and all(by[c]["class"] == "personal" for c in hashed)
    assert by["hmac_key_version"]["class"] == "internal"
    assert by["producer_owned"]["class"] == "public"          # derived from the presence of a public field


def test_every_personal_silver_column_is_masked_and_every_masked_column_is_personal():
    """Ties step 5 to step 4: the classification and the Unity Catalog masks cannot drift apart."""
    personal = {r["column"] for r in cl.silver_rows(SPEC) if r["class"] == "personal"}
    masks = set(yaml.safe_load((P5 / "policies.yml").read_text(encoding="utf-8"))["mask_columns"])
    assert personal == masks


def test_every_column_that_never_leaves_silver_is_personal_or_internal():
    for r in cl.silver_rows(SPEC):
        if r["never_leaves_silver"]:
            assert r["class"] in ("personal", "internal"), r["column"]


def test_gold_holds_no_personal_column_and_covers_every_model_of_the_comparison():
    from gold_lib.compare import MODELS
    assert set(GOLD) == set(MODELS)
    for model, cols in GOLD.items():
        assert cols and all(r["class"] != "personal" for r in cl.gold_rows(SPEC, model, cols)), model


def test_every_column_documented_in_the_gold_schema_file_exists():
    schema = yaml.safe_load((ROOT / "p4_modelling" / "models" / "portable" / "schema.yml").read_text(encoding="utf-8"))
    for m in schema["models"]:
        for c in m.get("columns") or []:
            assert c["name"] in GOLD[m["name"]], f"{m['name']}.{c['name']} is documented but not in the model"


def test_the_raw_bronze_record_and_the_quarantine_payload_are_personal():
    rows = {t["name"].split(".")[-1]: {r["column"]: r["class"] for r in cl.table_rows(SPEC, t, TABLES[t["name"]])} for t in SPEC["tables"]}
    assert rows["bronze_delta_raw"]["raw_json"] == "personal"
    assert rows["bronze_delta_raw"]["code"] == "public"
    assert rows["silver_quarantine"]["payload"] == "personal"
    assert rows["market_access"]["principal"] == "personal"
    assert rows["silver_taxonomy_tag"]["tag"] == "public" and rows["silver_taxonomy_tag"]["job_run_id"] == "internal"


def test_ddl_columns_handles_types_that_contain_commas():
    sql = "CREATE TABLE t (a STRING NOT NULL, b MAP<STRING,BIGINT>, c ARRAY<STRUCT<x:INT,y:STRING>>, d INT) USING DELTA"
    assert cl.ddl_columns(sql) == ["a", "b", "c", "d"]


# --- a planted mistake is found -------------------------------------------------------------------------------------------------------

def test_a_hashed_column_classified_public_is_found():
    bad = copy.deepcopy(SPEC)
    bad["silver_overrides"] = {"owner_hmac": {"class": "public"}}
    assert any("owner_hmac" in p and "hashed" in p for p in cl.problems(bad, TABLES, GOLD))


def test_a_table_missing_from_the_file_and_a_table_that_does_not_exist_are_found():
    bad = copy.deepcopy(SPEC)
    bad["tables"] = [t for t in bad["tables"] if not t["name"].endswith("bronze_manifest")]
    bad["tables"].append({"name": "workspace.x.ghost", "class": "internal", "why": "test"})
    out = "\n".join(cl.problems(bad, TABLES, GOLD))
    assert "bronze_manifest exists in the project but is not classified" in out and "ghost is classified but has no known definition" in out


def test_an_override_naming_a_column_that_does_not_exist_is_found():
    bad = copy.deepcopy(SPEC)
    bad["tables"][0]["columns"]["no_such_column"] = {"class": "personal"}
    bad["gold_overrides"]["product_history.no_such_column"] = {"class": "public"}
    out = "\n".join(cl.problems(bad, TABLES, GOLD))
    assert "no_such_column: override names a column that does not exist" in out and "product_history.no_such_column does not exist" in out


def test_a_personal_gold_column_is_found():
    bad = copy.deepcopy(SPEC)
    bad["gold_overrides"]["product_history.distinct_editors"] = {"class": "personal"}
    assert any("gold product_history.distinct_editors is personal" in p for p in cl.problems(bad, TABLES, GOLD))


@pytest.mark.parametrize("change", [
    {"silver_mapping": {"key": "public", "public": "public", "hashed": "public", "derived": "public", "lineage": "internal"}},
    {"gold_default": "secret"},
    {"tables": [{"name": "a.b.c", "class": "internal"}]},
])
def test_a_bad_classification_file_is_refused(change):
    with pytest.raises(cl.SpecError):
        cl.validate({**SPEC, **change})


def test_a_stale_gold_column_list_changes_the_document():
    changed = json.loads(json.dumps(GOLD))
    changed["dim_brand"].append("new_column")
    assert cl.render(SPEC, TABLES, changed) != cl.render(SPEC, TABLES, GOLD)
