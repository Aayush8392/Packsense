"""OFF taxonomy snapshots -> rows of silver_taxonomy_tag (contracts/taxonomy.yml). Plain Python, no Spark, unit-tested on real excerpts.

  entries_to_load   which snapshots the capture's daily logs list that silver has not loaded yet
  verify_snapshot   the landed gzip file must hold exactly the JSON the capture hashed
  parse_snapshot    one snapshot -> rows: names, parents, children and the allowlisted properties only, text scrubbed
"""
import collections
import datetime as dt
import email.utils
import gzip
import hashlib
import json
import re
from pathlib import Path

import yaml

from . import contract as contract_lib
from . import personal, schema

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "taxonomy.yml"
REQUIRED = {"version", "table", "manifest_table", "landing_prefix", "props_allowlist", "tag_shape", "columns", "grain"}


def load(path=None) -> dict:
    c = yaml.safe_load(open(path or CONTRACT_PATH, encoding="utf-8"))
    validate(c)
    return c


def validate(c: dict) -> None:
    missing = REQUIRED - set(c)
    if missing:
        raise ValueError(f"taxonomy contract keys missing: {sorted(missing)}")
    if c["version"] != 1:
        raise ValueError(f"this code reads taxonomy contract version 1, found {c['version']}")
    for col in c["columns"]:
        if not {"name", "type", "nullable"} <= set(col):
            raise ValueError(f"column needs name, type and nullable: {col}")
    re.compile(c["tag_shape"])
    if not all(isinstance(p, str) for p in c["props_allowlist"]):
        raise ValueError("props_allowlist must be a list of property names")


def relocate(c: dict, silver_schema: str = None) -> dict:
    """The same contract with its two tables moved to another schema (dev and scratch runs)."""
    out = dict(c)
    for key in ("table", "manifest_table"):
        name = c[key]
        if silver_schema and name.startswith(contract_lib.SILVER_PREFIX + "."):
            out[key] = silver_schema + name[len(contract_lib.SILVER_PREFIX):]
    return out


def column_names(c: dict) -> list[str]:
    return [x["name"] for x in c["columns"]]


def table_sql(c: dict) -> str:
    return schema.silver_table_sql(c)


def manifest_sql(c: dict) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {c['manifest_table']} (
  snapshot STRING NOT NULL,
  taxonomy STRING NOT NULL,
  snapshot_sha256 STRING NOT NULL,
  tags_in BIGINT NOT NULL,
  tags_silver BIGINT NOT NULL,
  tags_skipped BIGINT NOT NULL,
  values_scrubbed BIGINT NOT NULL,
  processed_at TIMESTAMP NOT NULL,
  job_run_id STRING NOT NULL
) USING DELTA"""


def all_table_sql(c: dict) -> list[str]:
    return [table_sql(c), manifest_sql(c)]


# ---- which snapshots to load -----------------------------------------------------------------------------------------------

def parse_http_date(text):
    """An HTTP Last-Modified header -> naive UTC datetime; None when absent or unreadable."""
    if not text:
        return None
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return when.astimezone(dt.timezone.utc).replace(tzinfo=None) if when.tzinfo else when


def parse_iso(text):
    when = dt.datetime.fromisoformat(text)
    return when.astimezone(dt.timezone.utc).replace(tzinfo=None) if when.tzinfo else when


def entries_to_load(logs: list[dict], done: set, only=None) -> list[dict]:
    """Snapshots named in the daily logs (oldest log first) that are not in `done`, one per snapshot key.

    Every log repeats the unchanged snapshots, so the first log that names a snapshot decides its entry. valid_from is OFF's
    Last-Modified, else the capture time of that log. Ordered by valid_from then taxonomy, so older versions load first."""
    seen, out = set(), []
    for log in logs:
        for e in log.get("entries", []):
            key = e["snapshot"]
            if key in seen or key in done or (only and e["name"] not in only):
                continue
            seen.add(key)
            valid_from = parse_http_date(e.get("last_modified")) or parse_iso(log["captured_at"])
            out.append({"taxonomy": e["name"], "snapshot": key, "sha256": e["sha256"], "valid_from": valid_from,
                        "tags": e.get("tags")})
    return sorted(out, key=lambda x: (x["valid_from"], x["taxonomy"]))


def verify_snapshot(gz_bytes: bytes, entry: dict) -> bytes:
    """The raw JSON inside a landed snapshot; raises if it is not exactly what the capture hashed."""
    raw = gzip.decompress(gz_bytes)
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"{entry['snapshot']}: the landed file does not match the sha256 the capture recorded")
    return raw


# ---- one snapshot -> rows ------------------------------------------------------------------------------------------------

def _clean_text(text: str, patterns: dict, stats) -> str:
    out, n = personal.scrub(text, patterns)
    stats["values_scrubbed"] += n
    return out


def _lang_map(value, patterns, stats) -> dict:
    """{language: text} keeping only string entries; text scrubbed."""
    if not isinstance(value, dict):
        return {}
    return {lang: _clean_text(text, patterns, stats) for lang, text in value.items() if isinstance(lang, str) and isinstance(text, str)}


def _prop(value, patterns, stats):
    """An allowlisted property as one string: the English value, else the first language by code; None if it has no plain text."""
    if isinstance(value, str):
        return _clean_text(value, patterns, stats)
    values = _lang_map(value, patterns, stats)
    if not values:
        return None
    return values.get("en", values[min(values)])


def _tag_list(value, shape) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({t for t in value if isinstance(t, str) and shape.match(t)})


def parse_snapshot(taxonomy: str, raw: bytes, c: dict, silver_contract: dict):
    """Rows (dicts of the contract's data columns) and a counter of what happened to the snapshot's tags."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{taxonomy}: a taxonomy snapshot must be a JSON object of tags")
    shape = re.compile(c["tag_shape"])
    patterns = personal.compile_patterns(silver_contract)
    allowed = c["props_allowlist"]
    stats = collections.Counter()
    rows = []
    for tag, entry in data.items():
        stats["tags_in"] += 1
        if not (isinstance(tag, str) and shape.match(tag) and isinstance(entry, dict)):
            stats["tags_skipped"] += 1
            continue
        names = _lang_map(entry.get("name"), patterns, stats)
        props = {}
        for key in allowed:
            if key in entry:
                value = _prop(entry[key], patterns, stats)
                if value is not None:
                    props[key] = value
        rows.append({"taxonomy": taxonomy, "tag": tag, "name_en": names.get("en"), "names": names,
                     "parents": _tag_list(entry.get("parents"), shape), "children": _tag_list(entry.get("children"), shape),
                     "props": props})
        stats["tags_silver"] += 1
    return rows, stats
