"""Freeze record of ROUND 2 of the history-key repair test with the photo reader (written 2026-11-10, before any round-2 call): the hash of every file of the method, both prompts, the model,
the thresholds, the sampling procedure, the set files and the pass condition. (The earlier record, for the old hybrid C on the final block, was deleted before any sealed call.)

  python p8_steward/freeze_fix_test.py write     # writes output/review_set/freeze_fix_test.json (refuses to overwrite)
  python p8_steward/freeze_fix_test.py check     # recomputes and compares: exit 1 on any difference; the round-2 runner refuses to start unless this holds

The method: the frozen text reader (prompt v3rows, guard) and the photo reader (the same instruction written for a photo, resized to 1,600 px); a line is shown only when the two readings agree
(Rule 2) or the narrow rule and the photo agree (Rule 1); the line is the photo table; silence otherwise (photo_method.py).
The model name taken from every response is stored beside every reading ('model'); after the run `models_seen` must list only the frozen model.
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
import answer_key_lib as akl  # noqa: E402
import fix_test_agent as fa  # noqa: E402
import ocr_variant_test as ov  # noqa: E402
import photo_method as pm  # noqa: E402
import reader_decision as rd  # noqa: E402
import run_round2_readers as rr  # noqa: E402

SET = ROOT / "output" / "review_set"
OUT = SET / "freeze_fix_test.json"
FILES = ["p8_steward/answer_key_lib.py", "p8_steward/scan_layout.py", "p8_steward/reader_decision.py", "p8_steward/rule_evidence.py", "p8_steward/fix_candidates.py",
         "p8_steward/bootstrap/dev_ocr_reader.py", "p8_steward/gateway.py", "p8_steward/gateway_config.json", "p8_steward/fix_test_lib.py", "p8_steward/fix_test_agent.py",
         "p8_steward/history_key_scan_check.py", "p8_steward/review_set_lib.py", "p7_triage_ml/rules_lib.py",
         "p8_steward/photo_method.py", "p8_steward/vision_variant_test.py", "p8_steward/ocr_variant_test.py", "p8_steward/bootstrap/run_round2_readers.py"]
MODEL = pm.MODEL
SAMPLING = {"judging_order": "all shown lines in ONE shuffled order, by sha256('order-3:' + code); blind A/B (the photo table against the contributor's post-fix record), swap by the parity of sha256('swap-3:' + code)",
            "random_70": "derived mechanically BEFORE any judging and saved: the first 70 shown lines in sha256('judge-2:' + code) order; the 70 are not marked on the page",
            "owner_judges": "EVERY shown line, in the page's order, no skipping; 'can't tell' is excluded and reported (and counted as wrong as a sensitivity); 'neither' is wrong"}
PASS = {"primary_set": "round 2: the 214 products of fix_test_round2.json; lines shown by the rule type under test; the photo table is right when the owner chooses it or 'both'",
        "primary_result": "the FULL SET of shown lines: Wilson 95% lower bound at least 80% = pass",
        "check_result": "the pre-committed random 70: lower bound at least 70%; a gap of more than about 10 points to the full set is a warning of fatigue or a slipping standard and is looked into before either number is trusted",
        "branch": "full-set lower bound at least 80% = pass; 70 to 80% = near miss (look at the failures first; the final block is spent as part of that); below 70% = stop the photo path and ship the fallbacks",
        "line_types": list(pm.LINE_TYPES), "line_types_note": "nothing outside this list may be chosen after the results; round 2 is a selection round",
        "next_step": "after round 2 the owner may pick ONE line type from the list; it is frozen and tested once on the untouched FINAL block (fix_test_final.json, 400 products) at the same bar; only that result is a publishable claim",
        "reported_beside": ["coverage as observed, no re-weighting", "the comparison with the contributor on the same cases", "the 'differ' and 'match' counts", "the photo reading's accuracy on all products",
                            "scan timing and clean-versus-unclean key as sensitivities"]}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def models_seen(readings: dict) -> list[str]:
    """Every model name the responses carried (a reading without one is listed as None)."""
    return sorted({str(v.get("model")) for v in readings.values() if v.get("tokens")})


def record() -> dict:
    cfg = json.loads((ROOT / "p8_steward" / "gateway_config.json").read_text(encoding="utf-8"))
    round2, final_file, dev_file = SET / "fix_test_round2.json", SET / "fix_test_final.json", SET / "fix_test_dev.json"
    return {"method": "ROUND 2: text reader v3rows + photo reader, a line only when the readings agree",
            "files": {f: sha(ROOT / f) for f in FILES},
            "prompts": {"text_sha256": hashlib.sha256(pm.text_system().encode("utf-8")).hexdigest(), "photo_sha256": hashlib.sha256(pm.photo_system().encode("utf-8")).hexdigest()},
            "version": fa.VERSION, "options": sorted(rd.OPTIONS), "text_limit_chars": pm.TEXT_LIMIT,
            "reader": {"model": MODEL, "endpoint": fa.GEMINI, "pause_between_calls_s": fa.PAUSE, "steward_settings": cfg["roles"]["steward"], "key_variable": "GEMINI_API_KEY (name only)",
                       "json_retry": "on (the unusable-JSON retry only, text reader and photo reader)", "model_name_stored_with_every_reading": True,
                       "photo": {"long_side_px": pm.PHOTO_LONG_SIDE, "image_part": "data:image/jpeg;base64", "max_completion_tokens": 700, "temperature": 0.2, "pause_s": ov.PAUSE},
                       "max_calls_per_run": rr.DEFAULT_MAX_CALLS, "gemini_day_reset_utc_hour": rr.RESET_UTC_HOUR},
            "thresholds": {"agree_share": 0.9, "agree_min_shared_fields": 3, "ten_percent_rule_floors": {f: list(akl.TOLERANCE.get(f, (0.10, 0.05))) for f in ov.FIELDS}, "fields": list(ov.FIELDS)},
            "silence": list(pm.SILENCE),
            "sampling": SAMPLING,
            "round2_file_sha256": sha(round2), "round2_products": len(json.loads(round2.read_text(encoding="utf8"))),
            "dev_file_sha256": sha(dev_file), "final_file_sha256": sha(final_file), "final_products": len(json.loads(final_file.read_text(encoding="utf8"))),
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
