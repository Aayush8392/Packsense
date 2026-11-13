"""The structured line of the nightly job and its validator (A121 settled 2026-11-13).

A line is DATA, never prose: the site renders the sentence from fixed templates (the licence gate's 'no free text' rule for published files, settled with the owner). Columns:
  code        the barcode (8 to 14 digits)
  night       the date of the run (YYYY-MM-DD)
  line_type   'match' | 'differ'  (the photo table agrees with / differs from the stored values; photo_method)
  statement   'repaired' (the repaired record breaks no rule of ours) | 'bound' (a stored value breaks a hard law against a confirmed one) | 'open' (a rule is still broken, no bound)
              | 'checked' (the stored record broke no rule: the line only shows the photo values)
  basis       'per_100' (the pack prints per 100 g or ml) | 'per_serving_converted' (per serving only; scaled by a printed serving size in g or ml)
  values      the photo table, per 100 g or ml: {field: number} (guard v2 additions included)
  derived     partner values code derived (salt <-> sodium, kJ <-> kcal): {field: number}
  bounds      [{rule, stale_field, stored, confirmed_field, confirmed, kind}] for a 'bound' statement, else []
  record_hash sha256 of the stored per-100 record the line was computed from; the site shows the line only while the card's record still has this hash
"""
from __future__ import annotations

import hashlib
import json
import re

FIELDS = ("energy_kcal", "energy_kj", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt", "sodium")
COLUMNS = ["code", "night", "line_type", "statement", "basis", "values", "derived", "bounds", "record_hash"]
LINE_TYPES = {"match", "differ"}
STATEMENTS = {"repaired", "bound", "open", "checked"}
BASES = {"per_100", "per_serving_converted"}
BOUND_KEYS = {"rule", "stale_field", "stored", "confirmed_field", "confirmed", "kind"}
BOUND_RULES = {"saturated-fat-greater-than-fat", "sugars-plus-starch-greater-than-carbohydrates"}
BOUND_KINDS = {"at most", "at least"}
MAX_VALUE = 100000.0                 # kJ and mg-scale fields stay far below this
CODE = re.compile(r"^\d{8,14}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HASH = re.compile(r"^[0-9a-f]{64}$")


def record_hash(stored: dict) -> str:
    """sha256 of the stored per-100 values (the ten fields, rounded to 6 places, None left out), as canonical JSON."""
    canon = {f: round(float(stored[f]), 6) for f in FIELDS if stored.get(f) is not None}
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()


def basis_of(reading_basis: str | None) -> str:
    b = str(reading_basis or "")
    return "per_100" if b in ("per 100 g", "per 100 ml") else "per_serving_converted"


def _clean(values: dict) -> dict:
    return {f: round(float(v), 6) for f, v in values.items() if f in FIELDS and v is not None}


def build_line(code: str, night: str, table: dict, derived: dict, differs: bool, statement: str, bounds: list[dict], reading_basis: str | None, stored: dict) -> dict:
    return {"code": code, "night": night, "line_type": "differ" if differs else "match", "statement": statement, "basis": basis_of(reading_basis),
            "values": _clean(table), "derived": _clean(derived),
            "bounds": [{k: b[k] for k in sorted(BOUND_KEYS)} for b in bounds], "record_hash": record_hash(stored)}


def _numbers(d, name: str, out: list[str]) -> None:
    if not isinstance(d, dict):
        out.append(f"{name}: not an object")
        return
    for f, v in d.items():
        if f not in FIELDS:
            out.append(f"{name}: unknown field")
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= MAX_VALUE:
            out.append(f"{name}: value of {f} out of range")


def validate_line(line: dict) -> list[str]:
    """The problems of a line (empty = valid). Never repeats a value; free text anywhere is a problem."""
    out: list[str] = []
    if sorted(line) != sorted(COLUMNS):
        return ["columns differ from the line columns"]
    if not (isinstance(line["code"], str) and CODE.match(line["code"])):
        out.append("code is not 8 to 14 digits")
    if not (isinstance(line["night"], str) and DATE.match(line["night"])):
        out.append("night is not a date")
    if line["line_type"] not in LINE_TYPES:
        out.append("line_type not allowed")
    if line["statement"] not in STATEMENTS:
        out.append("statement not allowed")
    if line["basis"] not in BASES:
        out.append("basis not allowed")
    if not (isinstance(line["record_hash"], str) and HASH.match(line["record_hash"])):
        out.append("record_hash is not a sha256")
    _numbers(line["values"], "values", out)
    _numbers(line["derived"], "derived", out)
    if isinstance(line["values"], dict) and len(line["values"]) < 3:
        out.append("values: fewer than 3 fields")
    if not isinstance(line["bounds"], list):
        out.append("bounds: not a list")
    else:
        for b in line["bounds"]:
            if not isinstance(b, dict) or set(b) != BOUND_KEYS:
                out.append("bounds: wrong keys")
                continue
            if b["rule"] not in BOUND_RULES or b["kind"] not in BOUND_KINDS or b["stale_field"] not in FIELDS or b["confirmed_field"] not in FIELDS:
                out.append("bounds: value not allowed")
            for k in ("stored", "confirmed"):
                if isinstance(b[k], bool) or not isinstance(b[k], (int, float)) or not 0 <= b[k] <= MAX_VALUE:
                    out.append(f"bounds: {k} out of range")
    if line["statement"] == "bound" and not line["bounds"]:
        out.append("a bound statement needs a bound")
    if line["statement"] != "bound" and line["bounds"]:
        out.append("bounds only belong to a bound statement")
    return out
