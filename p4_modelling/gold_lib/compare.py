"""Engine comparison: the portable gold models must give identical rows on Databricks and on DuckDB.

Each row is reduced to a canonical form (the same Python values whichever engine produced them) and hashed; the golden file holds
one md5 per row key, from the Databricks run. A DuckDB run is compared against it row by row. Canonical rules:
  integers (any width) -> int; floats -> float; booleans -> bool; timestamps -> 'YYYY-MM-DD HH:MM:SS' (UTC, whole seconds);
  dates -> 'YYYY-MM-DD'; arrays keep their order; maps and structs -> objects with sorted keys; NULL -> null.
"""
import datetime as dt
import decimal
import hashlib
import json
import re

# model -> the columns that identify a row (checked unique on both sides)
MODELS = {
    "product_history": ["history_key"],
    "product_flag_spans": ["flag_id"],
    "product_status": ["code"],
    "dim_brand": ["brand_key"],
    "dim_market": ["market_code"],
    "bridge_product_market": ["history_key", "market_code"],
    "dim_date": ["date_key"],
    "dim_flag": ["flag"],
    "taxonomy_tag_latest": ["taxonomy", "tag"],
    "bridge_product_allergen": ["history_key", "relationship", "allergen_tag"],
    "dim_allergen": ["allergen_tag"],
    "mart_allergen_change_log": ["change_key"],
}

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")


def norm(value):
    """A value as either engine's Python driver returns it -> the canonical Python value."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return value
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [norm(v) for v in value]
    if isinstance(value, dict):
        return {str(k): norm(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    raise TypeError(f"no canonical form for {type(value).__name__}")


def _split_top_level(text):
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def coerce_nested(value, type_text):
    """A value parsed from the JSON text of a Databricks ARRAY, MAP or STRUCT cell, typed by the manifest's `type_text`.
    The statement API renders every number inside a nested value as text ('9.88'); this gives each leaf its declared type back."""
    t = type_text.strip()
    low = t.lower()
    if value is None:
        return None
    if low.startswith("array<") and t.endswith(">"):
        return [coerce_nested(v, t[6:-1]) for v in value]
    if low.startswith("map<") and t.endswith(">"):
        _, vt = _split_top_level(t[4:-1])
        return {k: coerce_nested(v, vt) for k, v in value.items()}
    if low.startswith("struct<") and t.endswith(">"):
        types = {}
        for f in _split_top_level(t[7:-1]):
            name, ftype = f.split(":", 1)
            types[name.strip()] = ftype
        return {k: coerce_nested(v, types[k]) if k in types else v for k, v in value.items()}
    if not isinstance(value, str):
        return value    # already a JSON number or boolean
    leaf = {"bigint": "LONG", "tinyint": "BYTE", "smallint": "SHORT"}.get(low, "DECIMAL" if low.startswith("decimal") else low.upper())
    return from_databricks(value, leaf)


def from_databricks(text, type_name, type_text=None):
    """One cell of a Databricks statement result (JSON strings, typed by the result manifest) -> a Python value."""
    if text is None:
        return None
    t = type_name.upper()
    if t in ("BYTE", "SHORT", "INT", "LONG"):
        return int(text)
    if t in ("FLOAT", "DOUBLE"):
        return float(text)
    if t == "DECIMAL":
        return decimal.Decimal(text)
    if t == "BOOLEAN":
        return text.lower() == "true"
    if t == "TIMESTAMP":
        m = _TS.match(text)
        if not m:
            raise ValueError(f"unreadable timestamp {text!r}")
        return f"{m.group(1)} {m.group(2)}"
    if t == "DATE":
        return text[:10]
    if t in ("ARRAY", "MAP", "STRUCT"):
        parsed = json.loads(text)
        return coerce_nested(parsed, type_text) if type_text else parsed
    return text


def row_hash(row: dict) -> str:
    return hashlib.md5(json.dumps({k: norm(v) for k, v in row.items()}, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()


def key_of(row: dict, key_cols) -> str:
    return "|".join(str(norm(row[c])) for c in key_cols)


def summarise(model: str, columns: list, rows: list) -> dict:
    """{'columns': [...], 'rows': n, 'hashes': {key: md5}} for one model; raises if the key is not unique."""
    key_cols = MODELS[model]
    hashes = {}
    for row in rows:
        k = key_of(row, key_cols)
        if k in hashes:
            raise ValueError(f"{model}: key {k!r} is not unique")
        hashes[k] = row_hash(row)
    return {"columns": sorted(columns), "rows": len(rows), "hashes": hashes}


def diff(golden: dict, other: dict, limit: int = 10) -> list:
    """Human-readable differences between two summaries of the same models; empty when identical."""
    problems = []
    for model in MODELS:
        g, o = golden.get(model), other.get(model)
        if g is None or o is None:
            problems.append(f"{model}: missing on one side")
            continue
        if g["columns"] != o["columns"]:
            problems.append(f"{model}: columns differ: only golden {sorted(set(g['columns']) - set(o['columns']))}, "
                            f"only other {sorted(set(o['columns']) - set(g['columns']))}")
        if g["rows"] != o["rows"]:
            problems.append(f"{model}: row count {g['rows']} (golden) vs {o['rows']}")
        gk, ok = set(g["hashes"]), set(o["hashes"])
        for label, keys in (("only in golden", sorted(gk - ok)), ("only in other", sorted(ok - gk))):
            if keys:
                problems.append(f"{model}: {len(keys)} keys {label}, e.g. {keys[:limit]}")
        changed = sorted(k for k in gk & ok if g["hashes"][k] != o["hashes"][k])
        if changed:
            problems.append(f"{model}: {len(changed)} rows differ, e.g. {changed[:limit]}")
    return problems


def column_diff(row_a: dict, row_b: dict) -> list:
    """Names of the columns whose canonical values differ between two rows (for diagnostics)."""
    cols = set(row_a) | set(row_b)
    return sorted(c for c in cols if norm(row_a.get(c)) != norm(row_b.get(c)))
