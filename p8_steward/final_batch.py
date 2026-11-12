"""Splits the 400-product final block into batch A (the first 200 in a fixed hash order, read first) and batch B (the other 200, held in reserve for the pre-written extension).

  python p8_steward/final_batch.py write      writes fix_test_final_a.json and fix_test_final_b.json (refuses to overwrite)

Order: sha256('final-batch-1:' + code). Chosen and written before any final-block reader call; nothing about the products' content enters it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "output" / "review_set"
A, B = R / "fix_test_final_a.json", R / "fix_test_final_b.json"


def order(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: hashlib.sha256(("final-batch-1:" + r["code"]).encode()).hexdigest())


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    o = order(rows)
    return o[:200], o[200:]


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "write":
        sys.exit(__doc__)
    if A.exists() or B.exists():
        sys.exit("batch files exist: never overwritten")
    a, b = split(json.loads((R / "fix_test_final.json").read_text(encoding="utf8")))
    A.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    B.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", len(a), len(b))


if __name__ == "__main__":
    main()
