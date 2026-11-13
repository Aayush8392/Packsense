"""The candidate export of the nightly photo-reading job (A123, session 49): pure code that turns silver rows into `input/candidates.json`.

The Databricks notebook (`p8_steward/notebooks/export_nightly_candidates.py`) runs `candidate_sql()` on silver, reads the previous `candidates.json` from the private results
dataset, calls `build_document()` and uploads the result. Nothing here talks to a service.

A candidate is an India product whose NEWEST silver version still carries an OFF error flag about the nutrition table (`en:nutrition-...`). Its `stored` record is that
version's per-100 values (the ten fields of `line_record.FIELDS`, a missing value left out). Products with no recorded basis (`nutrition_per` empty: the legacy format) are left
out and counted, because their values may not be per 100. A product is `new` when it was not in the previous export (the very first export marks nobody new).

Safety: an empty result, or one smaller than MIN_SHARE of the previous export, is refused (`ExportRefused`): the old file stays, the nightly job's 2-day staleness check then
makes a silent night. The same value rules as `store._clean_candidate` are applied here, so the file never fails the store's own validation.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nightly import line_record as lr  # noqa: E402

SILVER_TABLE = "workspace.packsense_silver.silver_product_versions"
PREFIX = "en:nutrition-"
MIN_SHARE = 0.7


class ExportRefused(Exception):
    pass


def candidate_sql(table: str = SILVER_TABLE) -> str:
    """Spark SQL: one row per product, from its newest version, India only, with an open nutrition ERROR flag."""
    cols = ", ".join(lr.FIELDS)
    return f"""
with ranked as (
    select code, nutrition_per, countries_tags, data_quality_errors_tags, {cols},
           row_number() over (partition by code order by last_modified_t desc) as rn
    from {table}
)
select code, nutrition_per, {cols}
from ranked
where rn = 1
  and array_contains(countries_tags, 'en:india')
  and exists(data_quality_errors_tags, t -> t like '{PREFIX}%')
"""


def _stored(row: dict) -> dict | None:
    """The per-100 record of one row, or None when a value is unusable (the same rules as the store)."""
    out = {}
    for f in lr.FIELDS:
        v = row.get(f)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(v) or not 0 <= v <= lr.MAX_VALUE:
            return None
        out[f] = v
    return out


def build_document(rows: list[dict], previous: dict | None, exported: str, min_share: float = MIN_SHARE) -> tuple[dict, dict]:
    """(document, counts). `rows`: dicts with `code`, `nutrition_per` and the ten fields. `previous`: the earlier candidates.json (or None on the first export)."""
    prev_codes = None
    prev_n = 0
    if previous is not None:
        prev_rows = previous.get("candidates") if isinstance(previous, dict) else None
        if isinstance(prev_rows, list):
            prev_codes = {r.get("code") for r in prev_rows if isinstance(r, dict)}
            prev_n = len(prev_codes)
    counts = {"rows": len(rows), "no_basis": 0, "bad_code": 0, "bad_value": 0, "no_values": 0, "duplicate": 0, "exported": 0, "new": 0, "previous": prev_n}
    seen: set[str] = set()
    cands = []
    for r in rows:
        code = r.get("code")
        if not (isinstance(code, str) and lr.CODE.match(code)):
            counts["bad_code"] += 1
            continue
        if code in seen:
            counts["duplicate"] += 1
            continue
        if not r.get("nutrition_per"):
            counts["no_basis"] += 1
            continue
        stored = _stored(r)
        if stored is None:
            counts["bad_value"] += 1
            continue
        if not stored:
            counts["no_values"] += 1
            continue
        seen.add(code)
        cands.append({"code": code, "stored": stored, "new": prev_codes is not None and code not in prev_codes})
    cands.sort(key=lambda c: c["code"])
    counts["exported"] = len(cands)
    counts["new"] = sum(c["new"] for c in cands)
    if not cands:
        raise ExportRefused("the export holds no candidates; the previous file is kept")
    if prev_n and len(cands) < min_share * prev_n:
        raise ExportRefused(f"the export holds {len(cands)} candidates against {prev_n} before (under {int(min_share * 100)}%); the previous file is kept")
    return {"exported": exported, "candidates": cands}, counts
