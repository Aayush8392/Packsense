"""The nightly canary (A121 settled 2026-11-13): about 10 products with known-right lines are read first each night; the night proceeds only if the readings still agree with the saved answers.

Pure comparison here; the reading itself is night.run_canary. A canary product that ends in silence or an error counts as a miss. A canary of zero products proves nothing and never passes.
The tolerance (`MAX_MISS`) is provisional, to be confirmed by the soak test; it is a parameter, not a magic number in the loop.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ocr_variant_test as ov  # noqa: E402

MAX_MISS = 1


def compare(produced: dict, expected: dict, max_miss: int = MAX_MISS) -> dict:
    """produced: code -> the shown table or None; expected: code -> the saved right table (same fields, per 100 g)."""
    if not expected:
        return {"total": 0, "agreed": 0, "missed": [], "passed": False, "reason": "no_canary"}
    missed = sorted(c for c, e in expected.items() if not produced.get(c) or not ov.agree(produced[c], e))
    return {"total": len(expected), "agreed": len(expected) - len(missed), "missed": missed, "passed": len(missed) <= max_miss, "reason": None if len(missed) <= max_miss else "too_many_misses"}
