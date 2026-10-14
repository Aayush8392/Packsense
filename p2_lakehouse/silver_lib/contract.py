"""Loads and validates the silver data contract (contracts/silver.yml)."""
import re
from pathlib import Path

import yaml

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "silver.yml"
CLASSES = {"key", "public", "hashed", "derived", "lineage"}
BASE_TYPES = {"string", "int", "bigint", "double", "boolean", "timestamp", "array", "map"}
REQUIRED = {"name", "from", "type", "nullable", "class"}


def load(path=None) -> dict:
    contract = yaml.safe_load(open(path or CONTRACT_PATH, encoding="utf-8"))
    validate(contract)
    return contract


def validate(c: dict) -> None:
    cols = c["columns"]
    names = [x["name"] for x in cols]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"duplicate columns: {dupes}")
    for x in cols:
        missing = REQUIRED - set(x)
        if missing:
            raise ValueError(f"column {x.get('name')}: missing {sorted(missing)}")
        if x["class"] not in CLASSES:
            raise ValueError(f"column {x['name']}: unknown class {x['class']}")
        if x["type"].split("<")[0] not in BASE_TYPES:
            raise ValueError(f"column {x['name']}: unknown type {x['type']}")
        if not isinstance(x["nullable"], bool):
            raise ValueError(f"column {x['name']}: nullable must be true or false")
    for g in c["grain"]:
        if g not in names:
            raise ValueError(f"grain column {g} is not a column")
    for k in ("email", "aadhaar", "pan"):
        re.compile(c["scrub"][k])
    personal = set(c["personal_source_fields"])
    for x in cols:
        if x["class"] == "hashed":
            src = x["from"].replace("$.", "")
            if src not in personal:
                raise ValueError(f"hashed column {x['name']} reads {src}, which is not in personal_source_fields")


def columns(c: dict) -> list[dict]:
    return c["columns"]


def text_columns(c: dict) -> list[str]:
    """Columns the personal-data check searches: kept string and array<string> columns, not key/derived/lineage/hashed."""
    return [x["name"] for x in c["columns"]
            if x["class"] == "public" and (x["type"] == "string" or x["type"] == "array<string>")]
