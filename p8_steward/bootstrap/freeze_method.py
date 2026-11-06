"""Writes the freeze record of the sealed test (A121 paragraph 8): the hash of every file of the method, the prompt, the options, the word-height bands, the model settings and the answer-key fingerprint.

  python p8_steward/bootstrap/freeze_method.py --part test --version v3rows           # writes output/review_set/freeze_<part>_<version>.json (refuses to overwrite)
  python p8_steward/bootstrap/freeze_method.py --part test --version v3rows --check   # recomputes and compares with the stored record: exit 1 on any difference

Run the check right before the reader and again after it; the record is the proof that nothing changed between.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_ocr_reader as dr  # noqa: E402
import reader_decision as rd  # noqa: E402

SET = ROOT / "output" / "review_set"
FILES = ["p8_steward/answer_key_lib.py", "p8_steward/scan_layout.py", "p8_steward/reader_decision.py", "p8_steward/rule_evidence.py",
         "p8_steward/bootstrap/dev_ocr_reader.py", "p8_steward/gateway.py", "p8_steward/gateway_config.json"]
BANDS_PX = [0, 15, 20, 30, 50]                       # band lower edges of the median word height: under 15, 15 to 20, 20 to 30, 30 to 50, 50 and up
BAND_RULE = {"min_keyed_proposals": 15, "wilson95_lower_bound_at_least": 0.80}
BAR = {"proposal_right_if": "every field of the flagged group within 10% of the key", "point_estimate_at_least": 0.90, "wilson95_lower_bound_at_least": 0.80, "inconclusive_below_proposals": 40}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(part: str, version: str) -> dict:
    cfg = json.loads((ROOT / "p8_steward" / "gateway_config.json").read_text(encoding="utf-8"))
    key_file = SET / f"answer_key_{part}_key.json"
    key = json.loads(key_file.read_text(encoding="utf-8"))
    return {
        "part": part, "version": version,
        "files": {f: sha(ROOT / f) for f in FILES},
        "prompt_sha256": hashlib.sha256(dr.SYSTEMS[version].encode("utf-8")).hexdigest(),
        "options": sorted(rd.OPTIONS),
        "steward_settings": cfg["roles"]["steward"] if "roles" in cfg else cfg.get("steward"),
        "feedback_retry": "off (only an unusable-JSON retry)", "pause_between_calls_s": 13, "scan_text_limit_chars": 6000,
        "bands_px_lower_edges": BANDS_PX, "band_rule": BAND_RULE, "bar": BAR,
        "key_file_sha256": sha(key_file), "key_fingerprint": hashlib.sha256(key_file.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:16],      # as make_answer_key.py prints it (text mode drops the Windows line ends)
        "usable_cards": sum(1 for e in key["cards"].values() if e["usable"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    ap.add_argument("--version", required=True, choices=sorted(dr.SYSTEMS))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    out = SET / f"freeze_{a.part}_{a.version}.json"
    now = record(a.part, a.version)
    if a.check:
        then = json.loads(out.read_text(encoding="utf-8"))["record"]
        diffs = [k for k in now if now[k] != then.get(k)]
        print("FREEZE HOLDS" if not diffs else f"FREEZE BROKEN: {diffs}")
        sys.exit(1 if diffs else 0)
    if out.exists():
        sys.exit(f"{out.name} already exists: a freeze is written once")
    out.write_text(json.dumps({"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "record": now}, indent=1), encoding="utf-8")
    print("freeze written:", out.name, "\n", json.dumps(now, indent=1))


if __name__ == "__main__":
    main()
