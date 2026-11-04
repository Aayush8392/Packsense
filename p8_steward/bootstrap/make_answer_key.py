"""Builds the owner's answer key for one part of the review set from its Label Studio project (item 23).

  python p8_steward/bootstrap/make_answer_key.py --project 36 --part dev [--ls-env D:/off-catalogue-platform/label_studio/.env] [--replace]

Exports the project's answers (read only), turns each card into per-100 values with answer_key_lib.key_entry, writes output/review_set/answer_key_<part>_key.json (gitignored) with a
sha256 fingerprint, and prints what the owner should look at: cards that cannot be used and why, and key entries that break an arithmetic rule (a typo, or the pack's own error), with
the card's position in the project and its Label Studio task id. An existing key is not overwritten without --replace, so a key that was already used is never changed by accident.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p7_triage_ml" / "labelling"))
import answer_key_lib as ak  # noqa: E402
import fix_candidates as fc  # noqa: E402

SET = ROOT / "output" / "review_set"


def export_project(project: int, ls_env: str) -> list[dict]:
    import create_project as cp
    session, headers = cp.login(ls_env)
    r = session.get(f"{cp.BASE}/api/projects/{project}/export?exportType=JSON&download_all_tasks=true", headers=headers, timeout=300)
    r.raise_for_status()
    return sorted(r.json(), key=lambda t: t["id"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--ls-env", default="D:/off-catalogue-platform/label_studio/.env")
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()
    out_file = SET / f"answer_key_{args.part}_key.json"
    if out_file.exists() and not args.replace:
        sys.exit(f"{out_file.name} exists: it may already have been used. Pass --replace to write a new one (the old fingerprint is printed first).")
    if out_file.exists():
        print("replacing a key with fingerprint", hashlib.sha256(out_file.read_bytes()).hexdigest()[:16])
    export = export_project(args.project, args.ls_env)
    (SET / f"answer_key_{args.part}_export_project{args.project}.json").write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    position = {t["data"]["code"]: i for i, t in enumerate(export, 1)}
    task_id = {t["data"]["code"]: t["id"] for t in export}
    key = ak.build_key(export)
    doc = {"what": f"the owner's answer key for the {args.part} cards of the steward review set (item 23): per-100 values read from the pack photos",
           "made_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "source": f"Label Studio project {args.project} export", "cards": key}
    body = json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1)
    out_file.write_text(body, encoding="utf-8")
    usable = {c: e for c, e in key.items() if e["usable"]}
    print(f"key written: {out_file.name}, fingerprint {hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}")
    print(f"cards in the project {len(export)} | answered {len(key)} | usable {len(usable)} | per group {dict(collections.Counter(e['group'][0] for e in usable.values()))}")
    print("basis chosen:", dict(collections.Counter(e["basis"] for e in key.values())))
    for code, e in key.items():
        if not e["usable"]:
            print(f"  not usable  card {position[code]:2d} (task id {task_id[code]}): {e['reason']}")
    unanswered = [c for c, t in ((t["data"]["code"], t) for t in export) if c not in key]
    if unanswered:
        print(f"  NOT ANSWERED yet: cards {[position[c] for c in unanswered]}")
    for code, e in usable.items():
        broken = fc.violations(e["per100"])
        if broken:
            print(f"  rule warning card {position[code]:2d} (task id {task_id[code]}) {sorted(x[:40] for x in broken)}: {e['per100']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
