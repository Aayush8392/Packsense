"""Loads and validates the silver data contract (contracts/silver.yml, version 4)."""
import copy
import re
from pathlib import Path

import yaml

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "silver.yml"
CLASSES = {"key", "public", "hashed", "derived", "lineage"}
BASE_TYPES = {"string", "int", "bigint", "double", "boolean", "timestamp", "array", "map"}
REQUIRED = {"name", "from", "type", "nullable", "class"}
SECTIONS = ("hmac", "personal_source_fields", "own_handle_redaction", "scrub", "shape", "parsing", "fingerprint",
            "quarantine_codes", "egress", "legacy_nutriments", "columns", "grain")
SCRUB_PATTERNS = ("email", "obfuscated_email", "social_link", "url", "at_handle", "aadhaar", "gstin", "pan")
SHAPES = ("tag", "nutrient_key", "enum", "unit", "modifier")
SILVER_PREFIX = "workspace.packsense_silver"
BRONZE_PREFIX = "workspace.packsense_bronze"


def load(path=None) -> dict:
    contract = yaml.safe_load(open(path or CONTRACT_PATH, encoding="utf-8"))
    validate(contract)
    return contract


def text_column_names(c: dict) -> list[str]:
    """Kept string and array<string> columns of class public: the free text and tags."""
    return [x["name"] for x in c["columns"] if x["class"] == "public" and x["type"] in ("string", "array<string>")]


def scrubbed_columns(c: dict) -> list[str]:
    return [x["name"] for x in c["columns"] if x.get("scrub")]


def validate(c: dict) -> None:
    missing = [s for s in SECTIONS if s not in c]
    if missing:
        raise ValueError(f"contract sections missing: {missing}")
    if c.get("version") != 4:
        raise ValueError(f"this code reads contract version 4, found {c.get('version')}")
    cols = c["columns"]
    names = [x["name"] for x in cols]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"duplicate columns: {dupes}")
    for x in cols:
        absent = REQUIRED - set(x)
        if absent:
            raise ValueError(f"column {x.get('name')}: missing {sorted(absent)}")
        if x["class"] not in CLASSES:
            raise ValueError(f"column {x['name']}: unknown class {x['class']}")
        if x["type"].split("<")[0] not in BASE_TYPES:
            raise ValueError(f"column {x['name']}: unknown type {x['type']}")
        if not isinstance(x["nullable"], bool):
            raise ValueError(f"column {x['name']}: nullable must be true or false")
        if x.get("egress") not in (None, "never"):
            raise ValueError(f"column {x['name']}: egress must be 'never' when set")
    for g in c["grain"]:
        if g not in names:
            raise ValueError(f"grain column {g} is not a column")
    for k in SCRUB_PATTERNS:
        re.compile(c["scrub"][k])
    if "replacement" not in c["scrub"]:
        raise ValueError("scrub.replacement missing")
    for k in SHAPES:
        re.compile(c["shape"][k])
    if "Q_PII_FOUND" in c["quarantine_codes"]:
        raise ValueError("quarantine is for broken records only: Q_PII_FOUND must not exist in contract v2")
    own = c["own_handle_redaction"]
    if not (isinstance(own["min_length"], int) and own["min_length"] >= 1 and own["sentinel"]):
        raise ValueError("own_handle_redaction needs an integer min_length and a sentinel")
    text = set(text_column_names(c))
    for col in own["columns"]:
        if col not in text:
            raise ValueError(f"own_handle_redaction.columns: {col} is not a kept text column")
    if "brands" in own["columns"]:
        raise ValueError("brands must stay out of own-handle redaction (producer accounts write their own brand)")
    for col in scrubbed_columns(c):
        if col not in text:
            raise ValueError(f"scrub: {col} is not a kept text column")
    personal = set(c["personal_source_fields"])
    for x in cols:
        if x["class"] == "hashed":
            src = x["from"].replace("$.", "")
            if src not in personal:
                raise ValueError(f"hashed column {x['name']} reads {src}, which is not in personal_source_fields")
            if x.get("egress") != "never":
                raise ValueError(f"hashed column {x['name']} must be egress: never")
    if not c["parsing"]["units"]:
        raise ValueError("parsing.units is empty")
    eg = c["egress"]
    if not (isinstance(eg["handle_min_length"], int) and isinstance(eg["ordinary_word_min_products"], int)):
        raise ValueError("egress needs integer handle_min_length and ordinary_word_min_products")
    leg = c["legacy_nutriments"]
    key_re, unit_re = (re.compile(c["shape"][k]) for k in ("nutrient_key", "unit"))
    allowed = leg["allowed_keys"]
    if not allowed or len(set(allowed)) != len(allowed):
        raise ValueError("legacy_nutriments.allowed_keys must be a non-empty list without duplicates")
    bad = [k for k in allowed if not key_re.match(k)]
    if bad:
        raise ValueError(f"legacy_nutriments.allowed_keys fail the nutrient_key shape: {bad}")
    if not leg["suffix"] or not leg["modifier_suffix"]:
        raise ValueError("legacy_nutriments needs suffix and modifier_suffix")
    stray = sorted(set(leg["units"]) - set(allowed))
    if stray:
        raise ValueError(f"legacy_nutriments.units names keys that are not allowed: {stray}")
    for unit in [leg["default_unit"], *leg["units"].values()]:
        if not unit_re.match(unit):
            raise ValueError(f"legacy_nutriments: unit {unit!r} fails the unit shape")
    if "" in [leg["default_unit"], *leg["units"].values()]:
        raise ValueError("legacy_nutriments: a unit must not be empty")


def relocate(c: dict, silver_schema: str = None, bronze_schema: str = None) -> dict:
    """A copy of the contract with the table names moved to other schemas (tests use a scratch schema)."""
    out = copy.deepcopy(c)

    def sw(name: str) -> str:
        if silver_schema and name.startswith(SILVER_PREFIX + "."):
            return silver_schema + name[len(SILVER_PREFIX):]
        if bronze_schema and name.startswith(BRONZE_PREFIX + "."):
            return bronze_schema + name[len(BRONZE_PREFIX):]
        return name
    for k in ("table", "quarantine_table", "manifest_table", "stats_table", "field_log_table", "source_table"):
        out[k] = sw(out[k])
    return out
