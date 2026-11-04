"""Development report (item 23): what the code-side candidate fixes do on the development cards, scored against the owner's answer key.

  python p8_steward/bootstrap/dev_report_candidates.py [--part dev]

Reads output/review_set/ (gitignored). DEVELOPMENT data: it may be looked at while the method is built. The test cards must not be run through this until the method is frozen.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import answer_key_lib as ak  # noqa: E402
import fix_candidates as fc  # noqa: E402

SET = ROOT / "output" / "review_set"


def load_rows() -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for line in (SET / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows.setdefault(r["code"], []).append(r)
    return {c: sorted(v, key=lambda r: r["last_modified_t"]) for c, v in rows.items()}


def main() -> None:
    key = json.loads((SET / "answer_key_dev_key.json").read_text(encoding="utf-8"))["cards"]
    rows = load_rows()
    table = []
    for code, entry in key.items():
        if not entry["usable"]:
            continue
        versions = rows[code]
        cur, prev = versions[-1], (versions[-2] if len(versions) > 1 else None)
        stored = fc.clean(cur)
        group = entry["group"]
        before = ak.matches_key_for_group(stored, entry["per100"], group)
        cands = fc.candidates(cur, prev, cur.get("serving_quantity"))
        hits = [i for i, c in enumerate(cands) if ak.matches_key_for_group(c["values"], entry["per100"], group)["match"]]
        table.append({"code": code, "group": group[0], "stored_right": before["match"], "wrong_fields": before["wrong"], "compared": before["compared"],
                      "n_candidates": len(cands), "first_hit_rank": (hits[0] + 1) if hits else None, "hit": bool(hits)})
    return table


if __name__ == "__main__":
    t = main()
    print(f"{'code':15} {'g':1} {'stored matches key':19} {'candidates':10} {'right one at'}")
    for r in t:
        print(f"{r['code']:15} {r['group']:1} {str(r['stored_right']):19} {r['n_candidates']:<10} {r['first_hit_rank'] or '-'}  {('wrong: ' + ','.join(r['wrong_fields'])) if not r['stored_right'] else ''}")
    n = len(t)
    stored_wrong = [r for r in t if not r["stored_right"] and r["compared"]]
    print(f"\ncards {n} | stored record already matches the key (flag is a false alarm or already right): {sum(r['stored_right'] for r in t)}"
          f" | stored record is wrong: {len(stored_wrong)} | nothing to compare: {sum(1 for r in t if not r['compared'])}")
    print(f"of the {len(stored_wrong)} wrong records: a candidate matches the key for {sum(r['hit'] for r in stored_wrong)}, with a shortlist of "
          f"{sorted(r['n_candidates'] for r in stored_wrong if r['hit'])}; no candidate at all for {sum(1 for r in stored_wrong if not r['n_candidates'])}")
