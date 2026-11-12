"""Final block, batch A: the rule check and the list 'matches the pack but fails the rules' (a script, not judging; written 2026-11-13, as the pre-registration says).

  python p8_steward/final_rulecheck.py     -> prints the counts and writes output/review_set/final_a_rulecheck.json

Repaired record = the stored (pre-fix) record + the confirmed line (the photo table, plus the values guard v2 recovered: guard_v2_results.json) + the partner values code derives
(repair_record.repaired_record: salt <-> sodium, kJ <-> kcal). The rule set is fix_candidates.violations. Counted over EVERY shown rule2 line (no judging needed) and, for 'matches but fails',
over the judged sample lines only (decoys are altered lines and never count).
Each flagged line carries one of three statements: REPAIRED (the repaired record breaks no rule: flag cleared), BOUND (a hard law breaks between a stored value and a confirmed one: 'the stored X
must be at most Y'), OPEN (anything else: the photo does not cover the flagged field, or the rule lies outside the hard laws). A pack can print impossible values: a violation after the repair is not
an error of the line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
import fix_candidates as fc  # noqa: E402
import fix_test_lib as t  # noqa: E402
import repair_record as rr  # noqa: E402

R = ROOT / "output" / "review_set"
OUT = R / "final_a_rulecheck.json"


def check(rows: dict, decisions: dict, key: dict, answers: dict, viol=fc.violations, before=t.before, repair=rr.repaired_record, extras: dict | None = None, bounds=rr.bound_statements) -> dict:
    """rows: code -> product row; decisions: code -> pm.decide result; key: code -> 'sample' | 'decoy'; answers: code -> right | wrong | unsure; extras: code -> {'added': {field: value}} from guard v2."""
    shown = [c for c, d in decisions.items() if d.get("rule2") and d.get("table") is not None]
    out = {"shown_rule2_lines": len(shown), "stored_record_breaks_a_rule": 0, "repaired_breaks_a_rule": 0, "flag_cleared": 0, "flag_not_cleared": 0, "stored_clean_repaired_breaks": 0,
           "statements": {"repaired": 0, "bound": 0, "open": 0}}
    fails, not_cleared, bound_lines = [], [], []
    for c in shown:
        b = before(rows[c])
        tab = {f: v for f, v in decisions[c]["table"].items() if v is not None}
        tab = {**tab, **((extras or {}).get(c) or {}).get("added", {})}
        rec, _ = repair(b, tab)
        vb, vr = viol(b), viol(rec)
        out["stored_record_breaks_a_rule"] += bool(vb)
        out["repaired_breaks_a_rule"] += bool(vr)
        if vb and not vr:
            out["flag_cleared"] += 1
            out["statements"]["repaired"] += 1
        if vb and vr:
            out["flag_not_cleared"] += 1
            not_cleared.append(c)
            bs = bounds(b, tab, set(vr))
            if bs:
                out["statements"]["bound"] += 1
                bound_lines.append({"code": c, "kind": key.get(c), "answer": answers.get(c), "statements": bs})
            else:
                out["statements"]["open"] += 1
        if vr and not vb:
            out["stored_clean_repaired_breaks"] += 1
        if vr:
            fails.append({"code": c, "kind": key.get(c), "answer": answers.get(c), "violations": [str(x)[:140] for x in vr][:3]})
    out["matches_the_pack_but_fails_the_rules"] = [f for f in fails if f["kind"] == "sample" and f["answer"] == "right"]
    out["fail_the_rules_other"] = [f for f in fails if not (f["kind"] == "sample" and f["answer"] == "right")]
    out["judged_right_lines"] = sum(1 for c in shown if key.get(c) == "sample" and answers.get(c) == "right")
    out["flag_not_cleared_codes"] = not_cleared
    out["bound_lines"] = bound_lines
    return out


def main() -> None:
    rows = {r["code"]: r for r in json.loads((R / "fix_test_final_a.json").read_text(encoding="utf8"))}
    dec = json.loads((R / "final_a_decisions.json").read_text(encoding="utf8"))
    key = json.loads((R / "final_a_key.json").read_text(encoding="utf8"))
    answers = json.loads((R / "fix_review_final_a_answers.json").read_text(encoding="utf8"))
    extras = json.loads((R / "guard_v2_results.json").read_text(encoding="utf8"))["final_a"]["lines_gaining_values"]
    res = check(rows, dec, key, answers, extras=extras)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf8")
    brief = {k: v for k, v in res.items() if not isinstance(v, list)}
    print(json.dumps(brief, indent=1))
    print("matches the pack but fails the rules:", len(res["matches_the_pack_but_fails_the_rules"]))
    for f in res["matches_the_pack_but_fails_the_rules"][:12]:
        print("  ", f["code"], f["violations"][:2])
    for b in res["bound_lines"]:
        print("  bound", b["code"], [s["text"] for s in b["statements"]])


if __name__ == "__main__":
    main()
