"""One raw bronze record -> one silver row, or one quarantine row with a coded reason.

Everything silver keeps is listed in contracts/silver.yml (version 4); this module reads that list and nothing else gets
through. Nothing here judges whether a word is a name: values are validated by shape, patterns with a clear shape are
scrubbed, the record's own contributor names are replaced, and a record is quarantined only if it cannot be loaded.
A value that does not fit its column becomes NULL and is counted; it never quarantines the row.
"""
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from . import personal

CODE_RE = re.compile(r"^[0-9]+$")
CORE_NUTRIENTS = {  # column -> key in nutrition.aggregated_set.nutrients
    "energy_kcal": "energy-kcal", "fat": "fat", "saturated_fat": "saturated-fat", "carbohydrates": "carbohydrates",
    "sugars": "sugars", "added_sugars": "added-sugars", "starch": "starch", "fiber": "fiber", "proteins": "proteins",
    "salt": "salt", "sodium": "sodium",
}
STRIP_FROM_NUTRITION = {"source_description", "value_string"}   # free text / duplicate text, never kept


@dataclass
class Context:
    contract: dict
    key: str                                   # the HMAC key (from the secret scope; never printed)
    patterns: dict = field(init=False)
    shapes: dict = field(init=False)
    units: dict = field(init=False)
    personal_fields: list = field(init=False)
    redact_cols: frozenset = field(init=False)
    redact_min: int = field(init=False)
    sentinel: str = field(init=False)
    key_version: int = field(init=False)
    cols: list = field(init=False)
    legacy: dict = field(init=False)
    legacy_allowed: frozenset = field(init=False)
    field_counts: Counter = field(default_factory=Counter)   # top-level fields seen, for the drift monitor

    def __post_init__(self):
        c = self.contract
        self.patterns = personal.compile_patterns(c)
        self.shapes = personal.compile_shapes(c)
        self.units = c["parsing"]["units"]
        self.personal_fields = c["personal_source_fields"]
        own = c["own_handle_redaction"]
        self.redact_cols = frozenset(own["columns"])
        self.redact_min = own["min_length"]
        self.sentinel = own["sentinel"]
        self.key_version = c["hmac"]["key_version"]
        self.cols = c["columns"]
        self.legacy = c["legacy_nutriments"]
        self.legacy_allowed = frozenset(self.legacy["allowed_keys"])


@dataclass
class Result:
    kind: str                                  # "silver" | "quarantine"
    code: str = None
    last_modified_t: int = None
    row: dict = None
    reason: str = None
    payload: str = None                        # quarantine: scrubbed JSON, restricted to the contract's fields
    coerce_failures: Counter = field(default_factory=Counter)
    scrubbed: int = 0                          # pattern substitutions
    own_handles_redacted: int = 0
    tags_dropped: Counter = field(default_factory=Counter)   # per tag column
    nutrient_entries_dropped: int = 0
    enums_nulled: int = 0


def get_path(d, path: str):
    cur = d
    for part in path[2:].split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def coerce(value, typ: str):
    """Returns (converted value, ok). None is always ok; a value that does not fit becomes (None, False)."""
    if value is None:
        return None, True
    if typ == "string":
        return (value, True) if isinstance(value, str) else (None, False)
    if typ in ("int", "bigint"):
        if isinstance(value, bool):
            return None, False
        if isinstance(value, int):
            return value, True
        if isinstance(value, float) and value == int(value):
            return int(value), True
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            return int(value), True
        return None, False
    if typ == "double":
        if isinstance(value, bool):
            return None, False
        if isinstance(value, (int, float)):
            return float(value), True
        if isinstance(value, str):
            try:
                f = float(value)
            except ValueError:
                return None, False
            return (f, True) if f == f and f not in (float("inf"), float("-inf")) else (None, False)
        return None, False
    if typ == "array<string>":
        return ([x for x in value if isinstance(x, str)], True) if isinstance(value, list) else (None, False)
    return value, True


def code_kind(code: str) -> str:
    return {8: "gtin8", 12: "gtin12", 13: "gtin13", 14: "gtin14"}.get(len(code), "other")


def root_field(col: dict):
    """The top-level raw field a column reads from ('$.nutrition.a.b' -> 'nutrition'); None for derived and lineage columns."""
    src = col["from"].split(", else")[0]
    return src[2:].split(".")[0] if src.startswith("$.") else None


class Counts:
    """What the shape checks changed in one record, so the caller can report it."""
    def __init__(self):
        self.nutrient_entries_dropped = 0
        self.enums_nulled = 0


def checked_enum(value, ctx: Context, counts: Counts):
    if value is None:
        return None
    if personal.shape_ok(value, ctx.shapes["enum"]):
        return value
    counts.enums_nulled += 1
    return None


def nutrient_entry(v, failures: Counter, ctx: Context, counts: Counts):
    if not isinstance(v, dict):
        return None
    val, ok = coerce(v.get("value"), "double")
    if not ok:
        failures["nutrients.value"] += 1
    unit = v.get("unit") if isinstance(v.get("unit"), str) and ctx.shapes["unit"].match(v.get("unit")) else None
    mod = v.get("modifier") if isinstance(v.get("modifier"), str) and ctx.shapes["modifier"].match(v.get("modifier")) else None
    if (v.get("unit") is not None and unit is None) or (v.get("modifier") is not None and mod is None):
        counts.enums_nulled += 1
    return {"value": val, "unit": unit, "modifier": mod}


def nutrient_map(nutrients, failures: Counter, ctx: Context, counts: Counts):
    if not isinstance(nutrients, dict):
        return None
    out = {}
    for k, v in nutrients.items():
        if isinstance(k, str) and ctx.shapes["nutrient_key"].match(k):
            out[k] = nutrient_entry(v, failures, ctx, counts)
        else:
            counts.nutrient_entries_dropped += 1
    return out


def legacy_nutrients(nutriments, failures: Counter, ctx: Context, counts: Counts) -> dict:
    """OFF's old nutrition object -> the same map as the new format's nutrients (contract section legacy_nutriments).

    Reads only `<allowed nutrient>_100g` keys. A value that is not a finite number is skipped and counted. Empty dict if
    nothing allowed is present, which also means the product is not 'legacy' (computed keys such as nova-group do not count).
    """
    spec, out = ctx.legacy, {}
    if not isinstance(nutriments, dict):
        return out
    suffix = spec["suffix"]
    for key, raw in nutriments.items():
        if not (isinstance(key, str) and key.endswith(suffix)):
            continue
        base = key[: -len(suffix)]
        if base not in ctx.legacy_allowed:
            continue
        value, ok = coerce(raw, "double")
        if not ok or value is None or value != value or value in (float("inf"), float("-inf")):
            failures["legacy_nutriments.value"] += 1
            continue
        modifier = nutriments.get(base + spec["modifier_suffix"])
        out[base] = nutrient_entry({"value": value, "unit": spec["units"].get(base, spec["default_unit"]),
                                    "modifier": modifier if isinstance(modifier, str) else None}, failures, ctx, counts)
    return out


def input_sets(sets, failures: Counter, ctx: Context, counts: Counts):
    if not isinstance(sets, list):
        return None
    out = []
    for s in sets:
        if not isinstance(s, dict):
            continue
        q, ok = coerce(s.get("per_quantity"), "double")
        if not ok:
            failures["input_sets.per_quantity"] += 1
        out.append({"source": checked_enum(coerce(s.get("source"), "string")[0], ctx, counts),
                    "per": checked_enum(coerce(s.get("per"), "string")[0], ctx, counts),
                    "per_quantity": q,
                    "per_unit": checked_enum(coerce(s.get("per_unit"), "string")[0], ctx, counts),
                    "preparation": checked_enum(coerce(s.get("preparation"), "string")[0], ctx, counts),
                    "nutrients": nutrient_map(s.get("nutrients"), failures, ctx, counts)})
    return out


def strip_keys(o, keys):
    if isinstance(o, dict):
        return {k: strip_keys(v, keys) for k, v in o.items() if k not in keys}
    if isinstance(o, list):
        return [strip_keys(v, keys) for v in o]
    return o


def scrub_leaves(o, ctx: Context):
    if isinstance(o, str):
        return personal.scrub(o, ctx.patterns)[0]
    if isinstance(o, list):
        return [scrub_leaves(v, ctx) for v in o]
    if isinstance(o, dict):
        return {k: scrub_leaves(v, ctx) for k, v in o.items()}
    return o


def quarantine_payload(d: dict, ctx: Context) -> str:
    """The record restricted to the fields the contract keeps, identities hashed and patterns scrubbed. Fields that are only
    read to be parsed or fingerprinted (quantity, serving size, ingredients) are left out: the payload carries no more free
    text than silver does. Never the whole raw record: usernames also hide inside fields silver drops (data_sources_tags)."""
    keep = {}
    for col in ctx.cols:
        if col["class"] not in ("public", "key", "hashed") or col.get("parse") or col.get("fingerprint"):
            continue
        root = root_field(col)
        if root:
            keep[root] = col["class"]
    own = personal.own_handles(d, ctx.personal_fields, ctx.redact_min)
    redact_roots = {root_field(col) for col in ctx.cols if col["name"] in ctx.redact_cols}
    out = {}
    for root, cls in keep.items():
        if root not in d:
            continue
        v = d[root]
        if cls == "hashed":
            out[root] = personal.hash_value(ctx.key, v)
        elif root == "nutrition":
            out[root] = scrub_leaves(strip_keys(v, STRIP_FROM_NUTRITION), ctx)
        else:
            out[root] = scrub_leaves(v, ctx)
            if root in redact_roots and isinstance(out[root], str):
                out[root] = personal.redact_handles(out[root], own, ctx.sentinel)[0]     # same treatment as silver
    nm = d.get("nutriments")
    if isinstance(nm, dict):          # the old-format object, restricted to the keys silver maps (numbers only)
        suffix = ctx.legacy["suffix"]
        kept = {k: v for k, v in nm.items() if isinstance(k, str) and k.endswith(suffix) and k[: -len(suffix)] in ctx.legacy_allowed
                and isinstance(v, (int, float)) and not isinstance(v, bool)}
        if kept:
            out["nutriments"] = kept
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def process(raw_json: str, ctx: Context, lineage: dict) -> Result:
    """lineage: source_file, file_sha256, bronze_ingested_at, silver_processed_at, job_run_id."""
    try:
        d = json.loads(raw_json)
    except Exception:
        return Result("quarantine", reason="Q_BAD_JSON")
    if not isinstance(d, dict):
        return Result("quarantine", reason="Q_NOT_OBJECT")

    ctx.field_counts.update(d.keys())
    code = d.get("code")
    lmt = d.get("last_modified_t")
    if not (isinstance(code, str) and CODE_RE.match(code)):
        return Result("quarantine", reason="Q_BAD_CODE", code=code if isinstance(code, str) else None,
                      payload=quarantine_payload(d, ctx))
    if isinstance(lmt, bool) or not isinstance(lmt, int):
        return Result("quarantine", reason="Q_BAD_LAST_MODIFIED", code=code, payload=quarantine_payload(d, ctx))
    try:
        return _build(d, code, lmt, ctx, lineage)
    except Exception:  # unforeseen shape: never lose the record, never crash the batch
        return Result("quarantine", reason="Q_TRANSFORM_ERROR", code=code, last_modified_t=lmt, payload=quarantine_payload(d, ctx))


def _build(d: dict, code: str, lmt: int, ctx: Context, lineage: dict) -> Result:
    res = Result("silver", code=code, last_modified_t=lmt)
    failures, counts = res.coerce_failures, Counts()
    agg = get_path(d, "$.nutrition.aggregated_set")
    agg = agg if isinstance(agg, dict) else {}
    # the new format wins; the old `nutriments` object is read only when there is no aggregated set
    legacy = {} if agg else legacy_nutrients(d.get("nutriments"), failures, ctx, counts)
    nutrition_format = "new" if agg else "legacy" if legacy else "none"
    nutrients = legacy if legacy else (agg.get("nutrients") if isinstance(agg.get("nutrients"), dict) else {})
    own = personal.own_handles(d, ctx.personal_fields, ctx.redact_min)
    units = ctx.units
    row = {}
    parsed_quantity = parsed_serving = None

    def nval(key):
        v = nutrients.get(key)
        return v.get("value") if isinstance(v, dict) else None

    for col in ctx.cols:
        name, cls, typ = col["name"], col["class"], col["type"]
        if cls in ("derived", "lineage"):
            continue
        if cls == "hashed":
            row[name] = personal.hash_value(ctx.key, d.get(col["from"].replace("$.", "")))
            continue
        ok = True
        if col.get("parse") == "quantity":
            if parsed_quantity is None:
                parsed_quantity = personal.parse_quantity(d.get("quantity"), units)
            row[name] = parsed_quantity[{"quantity_amount": 0, "quantity_unit": 1, "quantity_multiplier": 2}[name]]
        elif col.get("parse") == "serving":
            if parsed_serving is None:
                parsed_serving = personal.parse_serving(d.get("serving_size"), units)
            row[name] = parsed_serving[{"serving_amount": 0, "serving_unit": 1}[name]]
        elif col.get("fingerprint"):
            row[name] = personal.fingerprint(d.get("ingredients_text"))
        elif name == "energy_kj":
            raw = nval("energy-kj")
            raw = raw if raw is not None else nval("energy")
            row[name], ok = coerce(raw, "double")
        elif name in CORE_NUTRIENTS:
            row[name], ok = coerce(nval(CORE_NUTRIENTS[name]), "double")
        elif name == "nutrients":
            row[name] = legacy if nutrition_format == "legacy" else nutrient_map(agg.get("nutrients"), failures, ctx, counts)
        elif name == "input_sets":
            row[name] = input_sets(get_path(d, "$.nutrition.input_sets"), failures, ctx, counts)
        else:
            row[name], ok = coerce(get_path(d, col["from"]), typ)
            if col.get("shape_check") == "enum":
                row[name] = checked_enum(row[name], ctx, counts)
            if col.get("tag_check") == "shape" and isinstance(row[name], list):
                kept = [t for t in row[name] if personal.shape_ok(t, ctx.shapes["tag"])]
                if col.get("max_digit_run"):      # a long run of digits is no taxonomy id and can be a phone number (contract note, v4)
                    long_run = re.compile(r"\d{%d,}" % (col["max_digit_run"] + 1))
                    kept = [t for t in kept if not long_run.search(t)]
                if len(kept) != len(row[name]):
                    res.tags_dropped[name] += len(row[name]) - len(kept)
                scrubbed_tags = []
                for t in kept:                       # a well-formed tag can still hold a bare domain (en:www.example.com)
                    t, n = personal.scrub(t, ctx.patterns)
                    res.scrubbed += n
                    scrubbed_tags.append(t)
                row[name] = scrubbed_tags
        if not ok:
            failures[name] += 1
        if col.get("scrub") and isinstance(row[name], str):
            row[name], n = personal.scrub(row[name], ctx.patterns)
            res.scrubbed += n
        if name in ctx.redact_cols and isinstance(row[name], str):
            row[name], n = personal.redact_handles(row[name], own, ctx.sentinel)
            res.own_handles_redacted += n

    row["code_kind"] = code_kind(code)
    row["nutrition_format"] = nutrition_format
    if nutrition_format == "legacy":
        row["nutrition_preparation"] = "as_sold"      # the old format's prepared values are a different set of keys, not read
    owner = d.get("owner")
    row["producer_owned"] = isinstance(owner, str) and owner.strip() != ""
    row["hmac_key_version"] = ctx.key_version
    row["silver_contract_version"] = ctx.contract["version"]
    for k in ("source_file", "file_sha256", "bronze_ingested_at", "silver_processed_at", "job_run_id"):
        row[k] = lineage.get(k)
    res.row = row
    res.nutrient_entries_dropped = counts.nutrient_entries_dropped
    res.enums_nulled = counts.enums_nulled
    return res
