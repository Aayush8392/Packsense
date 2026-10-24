"""The final test of the frozen system on a fresh question set, run once, scored under the label views fixed in advance (see the FROZEN_*.txt files).

    <scratch venv>/Scripts/python.exe p6_serving/bot/final_eval.py <questions file> <labels file of labeller 1> <labels file of labeller 2> <ref prefix>

Views: HEADLINE = union of the two labellers under labeller/LABEL_CONVENTION.md; LABELLER2 = the stricter labeller alone (DeepSeek); LABELLER1 = the other labeller alone.
The matcher is the shipping one: MiniLM blend 0.7, answer threshold 0.50, margin 0.10, qmax question pieces for long messages, hubs and three-option pairs, off-topic cues.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import cross_validate as cv  # noqa: E402
import evaluate_v2 as ev  # noqa: E402
import pooled_cv as pc  # noqa: E402

SHIP = (0.7, 0.50, 0.10)
DECLINE_RULES = ("refuse", "advice", "entry_or_refuse")


def parse(v: str) -> tuple[str, set]:
    """Label text -> (rule, accepted ids)."""
    v = v.strip()
    if v == "skip":
        return "skip", set()
    if v == "ADVICE":
        return "advice", set()
    if v.startswith("NONE"):
        ids = {x.strip() for x in v.partition(":")[2].split(",") if x.strip()}
        return "refuse", ids
    partial = v.endswith("?")
    ids = {x.strip() for x in v.rstrip("?").split(",") if x.strip()}
    return ("entry_or_refuse" if partial else "entry"), ids


def read_labels(path: Path) -> dict[str, str]:
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            ref, v = [x.strip() for x in ln.split("|", 1)]
            out[ref] = v
    return out


def combine(a: tuple[str, set], b: tuple[str, set]) -> tuple[str, set]:
    """The headline label: union of accepted entries; a decline is allowed when either labeller allows one."""
    if "skip" in (a[0], b[0]):
        return "skip", set()
    ids = a[1] | b[1]
    declines = [r in DECLINE_RULES for r in (a[0], b[0])]
    if not any(declines):
        return "entry", ids
    if all(r == "advice" for r in (a[0], b[0])):
        return "advice", set()
    if ids and not all(r in ("refuse", "advice") for r in (a[0], b[0])):
        return "entry_or_refuse", ids
    return "refuse", ids


def rows_for(view: str, prefix: str, questions: list[str], l1: dict, l2: dict) -> list[dict]:
    rows = []
    for i, line in enumerate(questions, 1):
        ref = f"{prefix}{i}"
        t = line.split("|", 1)[1].strip()
        first, _, last = t.rpartition("||")
        p1, p2 = parse(l1[ref]), parse(l2[ref])
        skip = "skip" in (p1[0], p2[0])
        rule, ids = ("skip", set()) if skip else {"HEADLINE": combine(p1, p2), "LABELLER2": p2, "LABELLER1": p1}[view]
        kind = "NEXT" if "||" in t else ("ON" if rule in ("entry", "entry_or_refuse") else "OFF")
        rows.append({"n": 3000 + i, "kind": kind, "text": last.strip(), "first": first.strip(), "prev": None, "accept": ids, "rule": rule,
                     "primary": sorted(ids)[0] if ids else None, "src": "fresh"})
    return rows


def main() -> None:
    qfile, f1, f2, prefix = sys.argv[1:5]
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    questions = [ln for ln in (HERE / qfile).read_text(encoding="utf-8").splitlines() if ln.strip()]
    l1, l2 = read_labels(HERE / f1), read_labels(HERE / f2)
    seen = [r for r in pc.load_pool("mine") if r["rule"] != "skip"]
    import segment_matcher as sm
    m = sm.SegmentMatcher(cv.MODEL, SHIP[0], cv.with_extra_wordings(entries, seen), fixed)
    cv.set_params(m, SHIP)
    prev = {}
    for i, line in enumerate(questions, 1):
        t = line.split("|", 1)[1].strip()
        if "||" in t:
            res = m.match(t.partition("||")[0].strip())
            prev[3000 + i] = res.entry_id if res.entry_id else (res.ranked[0][0] if res.ranked else None)
    for view in ("HEADLINE", "LABELLER2", "LABELLER1"):
        rows = rows_for(view, prefix, questions, l1, l2)
        for r in rows:
            r["prev"] = prev.get(r["n"])
        st, bad = ev.score(m, rows, follow)
        ev.report(st, f"=== {view} labels ({sum(1 for r in rows if r['rule'] != 'skip')} scored questions)")
        if view == "HEADLINE":
            for b in bad:
                print("   ", b)
    scored = [i for i in range(1, len(questions) + 1) if parse(l1[f"{prefix}{i}"])[0] != "skip"]
    agree = sum(1 for i in scored if parse(l1[f"{prefix}{i}"]) == parse(l2[f"{prefix}{i}"]))
    print(f"identical labels from the two labellers on {agree} of {len(scored)} scored questions")


if __name__ == "__main__":
    main()
