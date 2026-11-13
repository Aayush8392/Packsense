"""One-off: the INPUT files of the soak test's stages 0 and 1, built from the final block's batch A (gitignored working files in output/review_set/).

  python p8_steward/nightly/make_stage_inputs.py [--force]     writes output/nightly_inputs/candidates.json and canary.json (gitignored); prints counts only

  candidates.json  {"exported": date, "candidates": [{"code", "stored": the pre-fix per-100 record, "new": bool}]}   the batch A products without the canary ones; 20 are marked new by
                   sha256('stage-new:' + code) order, so the queue's new-first order is exercised
  canary.json      {"canary": [{"code", "stored", "expected": the photo table the final block showed}]}   10 lines the owner judged RIGHT (a sampled line, never a decoy), by sha256('stage-canary:' + code)

Batch A is used, not batch B: the readings of batch A are known, so a scratch night can be compared product by product with the saved final-block lines, and batch B stays unread.
Both files are uploaded by hand to the private results datasets (`input/` folder); nothing here talks to any service.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import fix_test_lib as t  # noqa: E402

R = ROOT / "output" / "review_set"
OUT = ROOT / "output" / "nightly_inputs"


def _order(code: str, salt: str) -> str:
    return hashlib.sha256((salt + code).encode()).hexdigest()


def build(rows: list[dict], decisions: dict, key: dict, answers: dict, n_canary: int = 10, n_new: int = 20, today: str | None = None) -> tuple[dict, dict]:
    """Pure: (candidates doc, canary doc). A canary line is a sampled line the owner judged right whose final-block decision showed a table (rule2)."""
    by_code = {r["code"]: r for r in rows}
    eligible = sorted((c for c, d in decisions.items() if c in by_code and d.get("rule2") and d.get("table") and key.get(c) == "sample" and answers.get(c) == "right"),
                      key=lambda c: _order(c, "stage-canary:"))
    if len(eligible) < n_canary:
        raise ValueError(f"only {len(eligible)} judged-right lines for a canary of {n_canary}")
    canary_codes = eligible[:n_canary]
    canary = [{"code": c, "stored": t.before(by_code[c]), "expected": {f: v for f, v in decisions[c]["table"].items() if v is not None}} for c in canary_codes]
    rest = sorted((c for c in by_code if c not in canary_codes), key=lambda c: _order(c, "stage-new:"))
    new = set(rest[:n_new])
    stamp = today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    cands = [{"code": c, "stored": t.before(by_code[c]), "new": c in new} for c in sorted(rest)]
    return {"exported": stamp, "candidates": cands}, {"canary": canary}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    a = ap.parse_args()
    load = lambda name: json.loads((R / name).read_text(encoding="utf-8"))  # noqa: E731
    cands, canary = build(load("fix_test_final_a.json"), load("final_a_decisions.json"), load("final_a_key.json"), load("fix_review_final_a_answers.json"))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, doc in (("candidates.json", cands), ("canary.json", canary)):
        p = OUT / name
        if p.exists() and not a.force:
            sys.exit(f"{p.name} exists: pass --force to overwrite")
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"candidates {len(cands['candidates'])} ({sum(c['new'] for c in cands['candidates'])} new), canary {len(canary['canary'])}; written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
