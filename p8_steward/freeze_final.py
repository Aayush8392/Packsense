"""Freeze record of the FINAL block (written 2026-11-12, before any final-block reader call). Round 2's record (freeze_fix_test.json) is never touched.

  python p8_steward/freeze_final.py write     writes output/review_set/freeze_final.json (refuses to overwrite)
  python p8_steward/freeze_final.py check     exit 1 on any difference; run_final_readers.py refuses to start unless this holds

It re-checks round 2's method hashes too (the method files are the same), so a change to any method file stops the run.
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
import freeze_fix_test as ff  # noqa: E402

R = ROOT / "output" / "review_set"
OUT = R / "freeze_final.json"
OWN = ["p8_steward/final_batch.py", "p8_steward/bootstrap/run_final_readers.py", "p8_steward/freeze_final.py"]
PRE = {
    "line_type": "rule2: a line is shown only when the text reading and the photo reading agree (photo_method.LINE_TYPES 'rule2'); the shown line is the photo table",
    "batches": "A = first 200 of the 400 in sha256('final-batch-1:' + code) order, read first; B = the other 200, reserve, read only if the extension rule applies",
    "judging": "the owner sees ONE line at a time: the photo and our line only (no contributor table, no stored values); answers right / wrong / can't tell",
    "sample": "from the shown rule2 lines of the read batches: the first 100 in sha256('final-judge:' + code) order (the sample); then 15 decoys from the lines outside the sample in "
              "sha256('final-decoy:' + code) order, each shown with its energy (kcal) value multiplied by 1.5 (rounded) so that the correct answer is 'wrong'; drawn and saved BEFORE judging; "
              "mixed with the sample by sha256('final-order:' + code); decoys are not marked",
    "decoy_use": "decoys measure attention only: a decoy judged 'right' is reported; they never enter the accuracy tally",
    "conventions": "as in round 2: only printed values decide (an unprinted value, even a 0, is neutral); '<x' accepts 0 or x; % under a per-100 g heading is grams per 100 g; 'both' within the 10% rule; "
                   "omissions of printed values are a completeness gap, not wrong; two-column 'as prepared / as sold' packs are excluded whatever the answer (listed with the answer given); "
                   "blurry deciding digits are 'can't tell'",
    "pass": "Wilson 95% lower bound of right / (right + wrong) over the 100 sampled lines at least 80%; can't-tell counted as wrong is reported as a sensitivity",
    "extension": "if that lower bound lands in 70 to 80%: read batch B, sample 100 more lines the same way (200 in all) and apply the same bar to all 200; below 70% = fail, 80% or more = pass; no other extension",
    "script_checks": "the rule check (our rule set on the stored record plus the photo table plus the code-derived partner fields) and the list 'matches the pack but fails the rules' come from a script, not from judging",
    "claim_wording": "anything public says: from a 214-product selection round, 98% matched the pack; the final block's own result is stated with its number of lines and its interval",
    "reported_beside": ["coverage as observed on the read batch", "silence reasons", "models_seen lists only the frozen model", "decoys caught"],
}


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def record() -> dict:
    return {"round2_method": ff.record(), "own_files": {f: sha(f) for f in OWN},
            "final_file_sha256": ff.sha(R / "fix_test_final.json"), "batch_a_sha256": ff.sha(R / "fix_test_final_a.json"), "batch_b_sha256": ff.sha(R / "fix_test_final_b.json"),
            "preregistration": PRE}


def problems() -> list[str]:
    if not OUT.exists():
        return ["no final freeze record"]
    then, now = json.loads(OUT.read_text(encoding="utf-8"))["record"], record()
    return sorted(k for k in set(now) | set(then) if now.get(k) != then.get(k))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "write":
        if OUT.exists():
            sys.exit(f"{OUT.name} exists: never overwritten")
        OUT.write_text(json.dumps({"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "record": record()}, indent=1, ensure_ascii=False), encoding="utf-8")
        print("written", OUT.name)
    elif cmd == "check":
        p = problems()
        print("FINAL FREEZE HOLDS" if not p else f"FINAL FREEZE BROKEN: {p}")
        sys.exit(1 if p else 0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
