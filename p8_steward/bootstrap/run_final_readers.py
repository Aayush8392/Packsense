"""Runs both readers over batch A of the final block (fix_test_final_a.json), only while the FINAL freeze record holds (freeze_final.py check).
Same method as round 2 (run_round2_readers.py, frozen), other set: it reuses that module with the set, photo folder and output file swapped.

  python p8_steward/bootstrap/run_final_readers.py plan [--batch a|b]
  python p8_steward/bootstrap/run_final_readers.py text  [--batch a|b] [--max-calls N]
  python p8_steward/bootstrap/run_final_readers.py photo [--batch a|b] [--max-calls N]

Batch B is the reserve: it runs only if the pre-written extension rule applies (freeze_final.json). The first error of any kind stops the run (503 retries are done by the caller).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_test_agent as fa  # noqa: E402
import photo_method as pm  # noqa: E402
import run_round2_readers as rr  # noqa: E402


def setup(batch: str) -> str:
    which = f"final_{batch}"
    rows_file = rr.R / f"fix_test_{which}.json"
    rr.PHOTOS = rr.R / "photos_final"
    rr.PHOTO_READINGS = rr.R / f"fix_test_photo_readings_{which}__{pm.MODEL}.json"
    rr.rows = lambda: json.loads(rows_file.read_text(encoding="utf8"))
    return which


def gate() -> None:
    import freeze_final as ffin
    problems = ffin.problems()
    if problems:
        sys.exit(f"FINAL FREEZE: {problems}; nothing runs")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "text", "photo"])
    ap.add_argument("--batch", default="a", choices=["a", "b"])
    ap.add_argument("--max-calls", type=int, default=rr.DEFAULT_MAX_CALLS)
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args()
    which = setup(a.batch)
    if a.cmd == "plan":
        rr.cmd_plan()
        return
    gate()
    rr.gate = lambda: None                                   # the final gate above replaces the round-2 one
    if a.cmd == "text":
        fa.run(which, pm.MODEL, a.max_calls, a.env_file)
    else:
        rr.cmd_photo(a.max_calls, a.env_file)


if __name__ == "__main__":
    main()
