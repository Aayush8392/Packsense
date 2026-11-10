"""Development slice of the history-key repair test: fix the split, run the CODE baseline on the development products (no model, no network).

  python p8_steward/fix_test_dev.py pick        -> output/review_set/fix_test_dev.json (150) and fix_test_sealed.json (the rest, in hash order; NOT opened by any proposer before the freeze)
  python p8_steward/fix_test_dev.py rounds      -> the clean-key sealed products in hash order: round1 (200) and round2 (214) are DEVELOPMENT rounds, final (400) stays untouched until the owner calls the method final
  python p8_steward/fix_test_dev.py baseline    -> three-way split of the code baseline on the development products
  python p8_steward/fix_test_dev.py adjudicate  -> for the code's alternatives: which side's values are printed in the scan
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fix_test_lib as t  # noqa: E402
import history_key_scan_check as hk  # noqa: E402

R = hk.REVIEW
DEV_N = 150


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pick":
        rows = [json.loads(line) for line in (R / "history_fix_candidates_v2.jsonl").read_text(encoding="utf8").splitlines()]
        keep = [r for r in rows if t.eligible(r)]
        ordered = hk.pick(keep, len(keep))
        dev, sealed = ordered[:DEV_N], ordered[DEV_N:]
        (R / "fix_test_dev.json").write_text(json.dumps(dev, ensure_ascii=False, sort_keys=True), encoding="utf8")
        (R / "fix_test_sealed.json").write_text(json.dumps(sealed, ensure_ascii=False, sort_keys=True), encoding="utf8")
        print(f"candidates {len(rows)}; dropped (only the per-serving column flagged) {len(rows) - len(keep)}; development {len(dev)}; sealed {len(sealed)}")
    elif cmd == "rounds":
        sealed = json.loads((R / "fix_test_sealed.json").read_text(encoding="utf8"))
        clean = [r for r in sealed if t.clean_key(r)]                     # already in hash order
        parts = {"round1": clean[:200], "round2": clean[200:414], "final": clean[414:]}
        for name, rows in parts.items():
            f = R / f"fix_test_{name}.json"
            if f.exists():
                sys.exit(f"{f.name} exists: the rounds are fixed once")
            f.write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True), encoding="utf8")
        print({k: len(v) for k, v in parts.items()}, "from", len(clean), "clean-key sealed products")
    elif cmd == "baseline":
        dev = json.loads((R / "fix_test_dev.json").read_text(encoding="utf8"))
        classes = [t.classify(r, t.code_proposal(r)) for r in dev]
        print(json.dumps(t.split(classes), indent=1))
        by_group: dict[str, list[str]] = {}
        for r, c in zip(dev, classes):
            by_group.setdefault(t.group_of_row(r), []).append(c)
        for g, cs in sorted(by_group.items()):
            print(g, len(cs), {k: cs.count(k) for k in ("agrees", "valid_alternative", "breaks_rule", "abstain")})
    elif cmd == "adjudicate":
        dev = json.loads((R / "fix_test_dev.json").read_text(encoding="utf8"))
        sides: dict[str, int] = {}
        for r in dev:
            proposal = t.code_proposal(r)
            if t.classify(r, proposal) != "valid_alternative":
                continue
            f = R / "ocr_json" / f"{r['code']}.json"
            side = t.printed_side(r, proposal, hk.scan_text(json.loads(f.read_text(encoding="utf8")))) if f.exists() else "no_scan_file"
            sides[side] = sides.get(side, 0) + 1
        print("code alternatives by which side is printed in the scan:", sides)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
