"""Guard v2 (pre-registered in output/review_set/guard_and_statements_prereg.md, 2026-11-13): the check that a photo number is printed in the OCR text, with one added step.

Today (answer_key_lib.grounded_values, frozen): a value counts only when it equals a number in the text (or 1000 x for the gram fields). v2 keeps that and, ONLY for a value that fails it, also accepts:
  (a) first-decimal rule: a value with one decimal (7.7) whose OCR token has more decimals and begins with it (7.79, 7.75; not 7.8);
  (b) trailing-9 rule: the OCR token is the value plus one extra '9' (14.9 -> 14.99, 81 -> 819: the 'g' read as a 9); a whole number needs a token of at least 3 digits.
Both only for non-energy fields, never for a 0, and the token must be UNIQUE for that value and not already the printed value of another field (the stand-in for row anchoring: the scan lines
cannot yet be matched to a nutrient). The value that stays in the reading is always the PHOTO's value, never the OCR token.

  with guard_v2.installed(): ...      replaces answer_key_lib.grounded_values for the block (the frozen file is not edited); recoveries are logged in guard_v2.LOG
"""
from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
import answer_key_lib as ak  # noqa: E402

LOG: list[dict] = []
_ORIGINAL = ak.grounded_values


def fmt(v: float) -> str:
    return "%g" % v


def tokens(text: str) -> list[str]:
    return sorted({t.replace(",", ".") for t in re.findall(r"\d+(?:[.,]\d+)?", text or "")})


def candidates(v: float, toks: list[str]) -> list[tuple[str, str]]:
    """(rule, token) for every OCR token that v2 would accept for the value v; empty for energy, zero or no match (the caller removes tokens another field already claims)."""
    s = fmt(v)
    out = []
    for t in toks:
        if "." in s and t != s and t.startswith(s) and "." in t and len(t) > len(s):
            out.append(("first_decimal", t))
        elif t == s + "9" and ("." in s or len(t) >= 3):
            out.append(("trailing_9", t))
    return out


def grounded_values_v2(values: dict, text: str) -> tuple[dict, list[str]]:
    kept, dropped = _ORIGINAL(values, text)
    if not dropped:
        return kept, dropped
    toks = tokens(text)
    claimed = {fmt(v) for v in kept.values()}
    still = []
    for f in dropped:
        v = values[f]
        found = []
        if f not in ak.ENERGY and v != 0:
            found = [(r, t) for r, t in candidates(v, toks) if t not in claimed]
        if len({t for _, t in found}) == 1:
            kept[f] = v
            LOG.append({"field": f, "value": v, "rule": found[0][0], "token": found[0][1]})
        else:
            still.append(f)
    return kept, still


@contextlib.contextmanager
def installed():
    ak.grounded_values = grounded_values_v2
    try:
        yield
    finally:
        ak.grounded_values = _ORIGINAL
