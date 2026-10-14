"""The silver contract file: structure and the guarantees the rest of the code relies on."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract  # noqa: E402


def test_loads_and_validates():
    c = contract.load()
    assert c["version"] == 1
    assert len(c["columns"]) == 68


def test_key_columns_are_not_nullable():
    cols = {x["name"]: x for x in contract.load()["columns"]}
    assert cols["code"]["nullable"] is False
    assert cols["last_modified_t"]["nullable"] is False
    assert contract.load()["grain"] == ["code", "last_modified_t"]


def test_dropped_fields_have_no_column():
    names = {x["name"] for x in contract.load()["columns"]}
    for dropped in ("images", "nutriments", "last_modified_by", "data_quality_tags", "owner_fields", "generic_name"):
        assert dropped not in names


def test_no_plain_username_column():
    # every column fed by a contributor field must be a hashed column
    c = contract.load()
    personal = set(c["personal_source_fields"])
    for x in c["columns"]:
        src = x["from"].replace("$.", "")
        if src in personal:
            assert x["class"] == "hashed" and x["name"].endswith("_hmac"), x["name"]


def test_text_columns_exclude_hashed_and_lineage():
    c = contract.load()
    text = set(contract.text_columns(c))
    assert "product_name" in text and "categories_tags" in text
    assert not any(n.endswith("_hmac") for n in text)
    assert "source_file" not in text and "code" not in text


def test_validate_rejects_a_duplicate_column():
    c = copy.deepcopy(contract.load())
    c["columns"].append(copy.deepcopy(c["columns"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        contract.validate(c)


def test_validate_rejects_a_hashed_column_reading_a_non_personal_field():
    c = copy.deepcopy(contract.load())
    col = next(x for x in c["columns"] if x["class"] == "hashed")
    col["from"] = "$.product_name"
    with pytest.raises(ValueError, match="personal_source_fields"):
        contract.validate(c)


def test_validate_rejects_an_unknown_class_and_type():
    c = copy.deepcopy(contract.load())
    c["columns"][0]["class"] = "secret"
    with pytest.raises(ValueError, match="class"):
        contract.validate(c)
    c = copy.deepcopy(contract.load())
    c["columns"][0]["type"] = "varchar"
    with pytest.raises(ValueError, match="type"):
        contract.validate(c)
