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
    pdc = c["personal_data_check"]
    if not (isinstance(pdc["min_username_length"], int) and isinstance(pdc["report_min_username_length"], int)
            and 1 <= pdc["report_min_username_length"] <= pdc["min_username_length"]):
        raise ValueError("report_min_username_length must be between 1 and min_username_length")
    text = {x["name"] for x in cols if x["class"] == "public" and x["type"] in ("string", "array<string>")}
    for col in pdc["own_contributor_exempt_columns"]:
        if col not in text:
            raise ValueError(f"own_contributor_exempt_columns: {col} is not a kept text column")
    if not stoplist_path(c).exists():
        raise ValueError(f"stoplist file not found: {pdc['stoplist']}")
    personal = set(c["personal_source_fields"])
    for x in cols:
        if x["class"] == "hashed":
            src = x["from"].replace("$.", "")
            if src not in personal:
                raise ValueError(f"hashed column {x['name']} reads {src}, which is not in personal_source_fields")


def stoplist_path(c: dict) -> Path:
    """The stoplist path in the contract is relative to the repository root."""
    return Path(__file__).resolve().parents[2] / c["personal_data_check"]["stoplist"]


SILVER_PREFIX = "workspace.packsense_silver"
BRONZE_PREFIX = "workspace.packsense_bronze"


def relocate(c: dict, silver_schema: str = None, bronze_schema: str = None) -> dict:
    """A copy of the contract with the table names moved to other schemas (tests use a scratch schema)."""
    import copy
    out = copy.deepcopy(c)

    def sw(name: str) -> str:
        if silver_schema and name.startswith(SILVER_PREFIX + "."):
            return silver_schema + name[len(SILVER_PREFIX):]
        if bronze_schema and name.startswith(BRONZE_PREFIX + "."):
            return bronze_schema + name[len(BRONZE_PREFIX):]
        return name
    for k in ("table", "quarantine_table", "manifest_table", "stats_table", "field_log_table", "source_table"):
        out[k] = sw(out[k])
    out["personal_data_check"]["identity_table"] = sw(out["personal_data_check"]["identity_table"])
    return out


def columns(c: dict) -> list[dict]:
    return c["columns"]


def text_columns(c: dict) -> list[str]:
    """Columns the personal-data check searches: kept string and array<string> columns, not key/derived/lineage/hashed."""
    return [x["name"] for x in c["columns"]
            if x["class"] == "public" and (x["type"] == "string" or x["type"] == "array<string>")]
