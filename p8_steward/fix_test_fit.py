"""Does each side 'fit in'? Run OFF's full rule set (p7_triage_ml/rules_lib.py, errors AND warnings) on the pre-fix record, the code's repaired record and the post-fix key.

  python p8_steward/fix_test_fit.py code      -> the code baseline on the development products, alternatives only

Counts per record: violated rules, and rules positively checked (status 'ok'; a rule whose inputs are missing is not_applicable and proves nothing). A record with more fields is tested by more rules.
Pairs of (code repaired, key) fall in: both_clean | key_clean_only | code_clean_only | both_violate. Rules cannot say which clean record matches the pack; a record that violates one is
inconsistent in itself. Separate figure, no pass mark.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_triage_ml"))
import fix_candidates as fc  # noqa: E402
import fix_test_lib as t  # noqa: E402
import history_key_scan_check as hk  # noqa: E402
import rules_lib as rl  # noqa: E402


def fit(values: dict) -> dict:
    v = rl.verdicts(fc.rule_input(values))
    return {"violated": sorted(n for n, x in v.items() if x.status == "violated"), "checked": sum(x.status == "ok" for x in v.values())}


def pair(code_fit: dict, key_fit: dict) -> str:
    c, k = not code_fit["violated"], not key_fit["violated"]
    return "both_clean" if c and k else "key_clean_only" if k else "code_clean_only" if c else "both_violate"


def main() -> None:
    dev = json.loads((hk.REVIEW / "fix_test_dev.json").read_text(encoding="utf8"))
    counts: dict[str, int] = {}
    checked = {"code": [], "key": []}
    examples = []
    for r in dev:
        proposal = t.code_proposal(r)
        if t.classify(r, proposal) != "valid_alternative":
            continue
        cf, kf = fit({**t.before(r), **proposal}), fit(t.key(r))
        p = pair(cf, kf)
        counts[p] = counts.get(p, 0) + 1
        checked["code"].append(cf["checked"])
        checked["key"].append(kf["checked"])
        if p != "both_clean" and len(examples) < 12:
            examples.append((r["code"], p, kf["violated"], cf["violated"]))
    n = sum(counts.values())
    print("alternatives:", n, counts)
    print("rules positively checked, mean: code", round(sum(checked["code"]) / n, 2), "key", round(sum(checked["key"]) / n, 2))
    for e in examples:
        print(e)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "code":
        main()
    else:
        sys.exit(__doc__)
