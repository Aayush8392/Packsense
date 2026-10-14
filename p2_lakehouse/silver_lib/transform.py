"""One raw bronze record -> one silver row, or one quarantine row with a coded reason.

Everything silver keeps is listed in contracts/silver.yml; this module reads that list and nothing else gets through.
A value that cannot be converted to its column type becomes NULL and is counted (it does not quarantine the row);
only the reasons in the contract's quarantine_codes do.
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
    known_users: frozenset = frozenset()       # HMACs of every contributor name seen so far
    known_phones: frozenset = frozenset()
    stoplist: frozenset = frozenset()          # ordinary words that are also usernames (normalised)
    patterns: dict = field(init=False)
    personal_fields: list = field(init=False)
    phone_prefixes: list = field(init=False)
    min_len: int = field(init=False)
    key_version: int = field(init=False)
    cols: list = field(init=False)
    text_cols: list = field(init=False)

    def __post_init__(self):
        c = self.contract
        self.patterns = personal.compile_patterns(c)
        self.personal_fields = c["personal_source_fields"]
        self.phone_prefixes = c["personal_data_check"]["known_phones_from"]
        self.min_len = c["personal_data_check"]["min_username_length"]
        self.key_version = c["hmac"]["key_version"]
        self.cols = c["columns"]
        self.text_cols = [x["name"] for x in self.cols
                          if x["class"] == "public" and x["type"] in ("string", "array<string>")]


@dataclass
class Result:
    kind: str                                  # "silver" | "quarantine"
    code: str = None
    last_modified_t: int = None
    row: dict = None
    reason: str = None
    payload: str = None                        # quarantine: scrubbed JSON, restricted to the contract's fields
    coerce_failures: Counter = field(default_factory=Counter)
    scrubbed: int = 0
    short_hits: int = 0
    pii_columns: list = field(default_factory=list)
    identities: dict = field(default_factory=dict)   # hmac -> name length, to add to the identity table
    phones: dict = field(default_factory=dict)


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


def nutrient_entry(v, failures: Counter):
    if not isinstance(v, dict):
        return None
    val, ok = coerce(v.get("value"), "double")
    if not ok:
        failures["nutrients.value"] += 1
    unit, _ = coerce(v.get("unit"), "string")
    mod, _ = coerce(v.get("modifier"), "string")
    return {"value": val, "unit": unit, "modifier": mod}


def nutrient_map(nutrients, failures: Counter):
    if not isinstance(nutrients, dict):
        return None
    return {k: nutrient_entry(v, failures) for k, v in nutrients.items() if isinstance(k, str)}


def input_sets(sets, failures: Counter):
    if not isinstance(sets, list):
        return None
    out = []
    for s in sets:
        if not isinstance(s, dict):
            continue
        q, ok = coerce(s.get("per_quantity"), "double")
        if not ok:
            failures["input_sets.per_quantity"] += 1
        out.append({"source": coerce(s.get("source"), "string")[0], "per": coerce(s.get("per"), "string")[0],
                    "per_quantity": q, "per_unit": coerce(s.get("per_unit"), "string")[0],
                    "preparation": coerce(s.get("preparation"), "string")[0],
                    "nutrients": nutrient_map(s.get("nutrients"), failures)})
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


def root_field(col: dict) -> str:
    """The top-level raw field a column reads from ('$.nutrition.a.b' -> 'nutrition'); None for derived columns."""
    src = col["from"]
    if not src.startswith("$."):
        return "nutrition" if src.startswith("$.nutrition") else None
    return src[2:].split(".")[0].split(",")[0]


def quarantine_payload(d: dict, ctx: Context, withheld: set) -> str:
    """The record restricted to the fields the contract keeps, with contributor names hashed, patterns scrubbed and
    any field that triggered the personal-data check withheld. Never the whole raw record: usernames also hide inside
    fields silver drops (found in data_sources_tags)."""
    keep = {}
    for col in ctx.cols:
        if col["class"] not in ("public", "key", "hashed"):
            continue
        src = col["from"]
        if "$." not in src:
            continue
        root = src.split(", else")[0].split("$.")[1].split(".")[0]
        keep[root] = col["class"]
    out = {}
    for root, cls in keep.items():
        if root not in d:
            continue
        v = d[root]
        if root in withheld:
            out[root] = "[withheld]"
        elif cls == "hashed":
            out[root] = personal.hash_value(ctx.key, v)
        elif root == "nutrition":
            out[root] = scrub_leaves(strip_keys(v, STRIP_FROM_NUTRITION), ctx)
        else:
            out[root] = scrub_leaves(v, ctx)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def _flatten(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


def process(raw_json: str, ctx: Context, lineage: dict) -> Result:
    """lineage: source_file, file_sha256, bronze_ingested_at, silver_processed_at, job_run_id."""
    try:
        d = json.loads(raw_json)
    except Exception:
        return Result("quarantine", reason="Q_BAD_JSON")
    if not isinstance(d, dict):
        return Result("quarantine", reason="Q_NOT_OBJECT")

    users, phones = personal.known_identities(d, ctx.key, ctx.personal_fields, ctx.phone_prefixes)
    code = d.get("code")
    lmt = d.get("last_modified_t")
    base = dict(identities=users, phones=phones)
    if not (isinstance(code, str) and CODE_RE.match(code)):
        return Result("quarantine", reason="Q_BAD_CODE", code=code if isinstance(code, str) else None,
                      payload=quarantine_payload(d, ctx, set()), **base)
    if isinstance(lmt, bool) or not isinstance(lmt, int):
        return Result("quarantine", reason="Q_BAD_LAST_MODIFIED", code=code,
                      payload=quarantine_payload(d, ctx, set()), **base)
    try:
        return _build(d, code, lmt, ctx, lineage, users, phones)
    except Exception as e:  # unforeseen shape: never lose the record, never crash the batch
        return Result("quarantine", reason="Q_TRANSFORM_ERROR", code=code, last_modified_t=lmt,
                      payload=quarantine_payload(d, ctx, set()), **base)


def _build(d: dict, code: str, lmt: int, ctx: Context, lineage: dict, users: dict, phones: dict) -> Result:
    failures, scrubbed = Counter(), 0
    agg = get_path(d, "$.nutrition.aggregated_set")
    agg = agg if isinstance(agg, dict) else {}
    nutrients = agg.get("nutrients") if isinstance(agg.get("nutrients"), dict) else {}
    row = {}

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
        if name == "energy_kj":
            raw = nval("energy-kj")
            raw = raw if raw is not None else nval("energy")
            row[name], ok = coerce(raw, "double")
        elif name in CORE_NUTRIENTS:
            row[name], ok = coerce(nval(CORE_NUTRIENTS[name]), "double")
        elif name == "nutrients":
            row[name], ok = nutrient_map(agg.get("nutrients"), failures), True
        elif name == "input_sets":
            row[name], ok = input_sets(get_path(d, "$.nutrition.input_sets"), failures), True
        else:
            row[name], ok = coerce(get_path(d, col["from"]), typ)
        if not ok:
            failures[name] += 1
        if col.get("scrub") and isinstance(row[name], str):
            row[name], n = personal.scrub(row[name], ctx.patterns)
            scrubbed += n

    row["code_kind"] = code_kind(code)
    row["nutrition_format"] = "new" if agg else "none"
    owner = d.get("owner")
    row["producer_owned"] = isinstance(owner, str) and owner.strip() != ""
    row["hmac_key_version"] = ctx.key_version
    row["silver_contract_version"] = ctx.contract["version"]
    for k in ("source_file", "file_sha256", "bronze_ingested_at", "silver_processed_at", "job_run_id"):
        row[k] = lineage.get(k)

    # personal-data check on every kept text column: known identities and phones, then patterns that survived
    all_users = ctx.known_users | users.keys()
    all_phones = ctx.known_phones | phones.keys()
    pii_cols, short_total = [], 0
    for name in ctx.text_cols:
        texts = _flatten(row.get(name))
        hits, short = personal.find_known(texts, ctx.key, all_users, all_phones, ctx.min_len, ctx.stoplist)
        short_total += short
        if hits or any(personal.has_pattern(t, ctx.patterns) for t in texts):
            pii_cols.append(name)
    if pii_cols:
        cols_by_name = {c["name"]: c for c in ctx.cols}
        withheld = {root_field(cols_by_name[n]) for n in pii_cols}
        return Result("quarantine", reason="Q_PII_FOUND", code=code, last_modified_t=lmt, pii_columns=pii_cols,
                      payload=quarantine_payload(d, ctx, {w for w in withheld if w}), scrubbed=scrubbed,
                      short_hits=short_total, coerce_failures=failures, identities=users, phones=phones)
    return Result("silver", code=code, last_modified_t=lmt, row=row, coerce_failures=failures, scrubbed=scrubbed,
                  short_hits=short_total, identities=users, phones=phones)
