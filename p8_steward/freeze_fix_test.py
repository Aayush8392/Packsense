"""Freeze record of the history-key repair test (owner's approval 2026-11-08): the hash of every file of the method, the prompt, the settings, the sealed set and the pass condition.

  python p8_steward/freeze_fix_test.py write     # writes output/review_set/freeze_fix_test.json (refuses to overwrite)
  python p8_steward/freeze_fix_test.py check     # recomputes and compares: exit 1 on any difference; the sealed run refuses to start unless this holds

The method frozen here is HYBRID B on the CLEAN-KEY sealed products: the model reads the scan (prompt of dev_ocr_reader, version v3rows), code drops unprinted values and decides
(reader_decision), code fills the stale unprinted partner (fix_test_lib.complete_partners), and when the repaired record still violates a rule the code's own first candidate is used.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import dev_ocr_reader as dr  # noqa: E402
import fix_test_agent as fa  # noqa: E402
import fix_test_lib as t  # noqa: E402
import reader_decision as rd  # noqa: E402

SET = ROOT / "output" / "review_set"
OUT = SET / "freeze_fix_test.json"
FILES = ["p8_steward/answer_key_lib.py", "p8_steward/scan_layout.py", "p8_steward/reader_decision.py", "p8_steward/rule_evidence.py", "p8_steward/fix_candidates.py",
         "p8_steward/bootstrap/dev_ocr_reader.py", "p8_steward/gateway.py", "p8_steward/gateway_config.json", "p8_steward/fix_test_lib.py", "p8_steward/fix_test_agent.py",
         "p8_steward/history_key_scan_check.py", "p8_steward/review_set_lib.py", "p7_triage_ml/rules_lib.py"]
MODEL = "gemini-3.5-flash-lite"
PASS = {"primary_set": "the FINAL block: clean-key products never run through any model before the freeze (the post-fix record passes every rule of rules_lib); rounds 1 and 2 are development",
        "primary_test": "paired difference in agreement with OFF's fix, HYBRID B against the code baseline: 95% lower bound above zero AND point estimate at least +3 points",
        "agreement_rule": "the repaired record agrees with the post-fix key on every compared field of the flagged group within the 10% rule",
        "public_claim_if_pass": "an aggregate sentence only (agreement with OFF's later fix, and the points gained over code alone); no per-product lines",
        "on_fail": "aggregate counts only; no retry on the same set; a new method needs a new set and the owner's decision",
        "reported_beside": ["the unfiltered row (only if every eligible product was run)", "the three-way split and the bracket", "near-miss share, later-history and rule-fit figures of the alternatives"],
        "inconclusive_below_clean_key_products": 300, "final_block_size": 400}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record() -> dict:
    cfg = json.loads((ROOT / "p8_steward" / "gateway_config.json").read_text(encoding="utf-8"))
    final_file, dev_file = SET / "fix_test_final.json", SET / "fix_test_dev.json"
    final = json.loads(final_file.read_text(encoding="utf8"))
    return {"method": "HYBRID B on the clean-key sealed set", "files": {f: sha(ROOT / f) for f in FILES},
            "prompt_sha256": hashlib.sha256(dr.SYSTEMS[fa.VERSION].encode("utf-8")).hexdigest(), "version": fa.VERSION, "options": sorted(rd.OPTIONS),
            "reader": {"model": MODEL, "endpoint": fa.GEMINI, "pause_between_calls_s": fa.PAUSE, "steward_settings": cfg["roles"]["steward"], "key_variable": "GEMINI_API_KEY (name only)",
                       "json_retry": "on (the unusable-JSON retry only)", "scan_text_limit_chars": 6000},
            "partners": [list(p) for p in t.PARTNERS],
            "dev_file_sha256": sha(dev_file), "final_file_sha256": sha(final_file), "final_products": len(final), "final_clean_key": sum(t.clean_key(r) for r in final),
            "pass_condition": PASS}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "write":
        if OUT.exists():
            sys.exit(f"{OUT.name} exists: a freeze record is never overwritten")
        OUT.write_text(json.dumps({"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "record": record()}, indent=1, ensure_ascii=False), encoding="utf-8")
        print("written", OUT.name)
    elif cmd == "check":
        then = json.loads(OUT.read_text(encoding="utf-8"))["record"]
        now = record()
        diffs = sorted(k for k in set(now) | set(then) if now.get(k) != then.get(k))
        print("FREEZE HOLDS" if not diffs else f"FREEZE BROKEN: {diffs}")
        sys.exit(1 if diffs else 0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
