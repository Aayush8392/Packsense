"""The freeze record of the nightly job (A121 settled 2026-11-13): a COMMITTED record of the method files, the two prompts and the pinned model name.

  python p8_steward/nightly/freeze_nightly.py write     writes p8_steward/nightly/freeze.json (refuses to overwrite)
  python p8_steward/nightly/freeze_nightly.py check     exit 1 on any difference; the nightly job refuses to run unless this holds

Unlike the older freeze records (gitignored, hashing the CRLF working copies of this Windows checkout) this one is hashed on LINE-ENDING-NORMALISED bytes, so the same record holds on a
Linux runner. `check_model` is the fail-closed model check: a response that names another model than the pinned one stops the night (a new model means a new freeze and a fresh judged sample).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import photo_method as pm  # noqa: E402
from nightly.budget import Stop  # noqa: E402

RECORD = ROOT / "p8_steward" / "nightly" / "freeze.json"
METHOD_FILES = [
    "p8_steward/answer_key_lib.py", "p8_steward/scan_layout.py", "p8_steward/reader_decision.py", "p8_steward/rule_evidence.py", "p8_steward/fix_candidates.py",
    "p8_steward/bootstrap/dev_ocr_reader.py", "p8_steward/gateway.py", "p8_steward/gateway_config.json", "p8_steward/fix_test_lib.py", "p8_steward/fix_test_agent.py",
    "p8_steward/history_key_scan_check.py", "p8_steward/review_set_lib.py", "p7_triage_ml/rules_lib.py",
    "p8_steward/photo_method.py", "p8_steward/vision_variant_test.py", "p8_steward/ocr_variant_test.py", "p8_steward/bootstrap/run_round2_readers.py",
    "p8_steward/guard_v2.py", "p8_steward/repair_record.py",
    "p8_steward/nightly/budget.py", "p8_steward/nightly/queue_lib.py", "p8_steward/nightly/line_record.py", "p8_steward/nightly/canary.py", "p8_steward/nightly/night.py",
    "p8_steward/nightly/freeze_nightly.py", "p8_steward/nightly/store.py", "p8_steward/nightly/run_nightly.py", "p8_steward/nightly/requirements.lock",
    "p8_steward/nightly/readers.py", "p8_steward/bootstrap/fetch_ocr_text.py", "p8_steward/bootstrap/fetch_round2_photos.py",
]


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def sha_file(root: Path, rel: str) -> str | None:
    p = root / rel
    return sha_bytes(p.read_bytes()) if p.exists() else None


def record(root: Path = ROOT, files: list[str] | None = None) -> dict:
    return {"model": pm.MODEL,
            "prompts": {"text": sha_bytes(pm.text_system().encode("utf-8")), "photo": sha_bytes(pm.photo_system().encode("utf-8"))},
            "files": {f: sha_file(root, f) for f in (METHOD_FILES if files is None else files)}}


def problems(path: Path = RECORD, root: Path = ROOT, files: list[str] | None = None) -> list[str]:
    """The names of everything that differs from the record (a file, 'model', 'prompts'); a missing record is one problem."""
    if not path.exists():
        return ["no freeze record"]
    then, now = json.loads(path.read_text(encoding="utf-8"))["record"], record(root, files)
    out = [k for k in ("model", "prompts") if now[k] != then.get(k)]
    out += sorted(f for f in set(now["files"]) | set(then.get("files", {})) if now["files"].get(f) != then.get("files", {}).get(f))
    return out


def check_model(returned: str | None, pinned: str | None = None) -> None:
    """Fail closed: a response that does not name exactly the pinned model ends the night."""
    if returned != (pinned or pm.MODEL):
        raise Stop("model_mismatch")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "write":
        if RECORD.exists():
            sys.exit(f"{RECORD.name} exists: never overwritten")
        RECORD.write_text(json.dumps({"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "record": record()}, indent=1, ensure_ascii=False), encoding="utf-8")
        print("written", RECORD.name)
    elif cmd == "check":
        p = problems()
        print("NIGHTLY FREEZE HOLDS" if not p else f"NIGHTLY FREEZE BROKEN: {p}")
        sys.exit(1 if p else 0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
