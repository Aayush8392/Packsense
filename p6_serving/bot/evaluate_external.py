"""Score the matcher on the independent question set written by ChatGPT (packsense_faq_test_questions.txt), using labels fixed BEFORE the run (external_labels.psv).

  <scratch venv>/Scripts/python.exe p6_serving/bot/evaluate_external.py --hybrid 0.7      # the frozen primary system
  python p6_serving/bot/evaluate_external.py                                                # keywords only, for reference

Label rules (line id | type | previous answer | accepted entries | rule):
  entry            an ON question or follow-up: right when the answer is one of the accepted entries
  entry_or_refuse  right when it is an accepted entry OR the bot declines (the site has no real answer)
  refuse           an OFF question: right when the bot declines, or answers with an accepted entry that is itself the right reply
  advice           an OFF health question: right only when the bot gives the advice or medical refusal (or an accepted entry)
A wrong confident answer is a direct answer from an entry that is not accepted.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import matcher as mt  # noqa: E402

REFUSALS = {"generic", "advice", "medical", "time", "ranking", "productfacts", "meta", "english_only", "private"}


def wilson(k: int, n: int, z: float = 1.96) -> str:
    if not n:
        return "n/a"
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100 * p:.1f}% ({100 * max(0, c - h):.1f} to {100 * min(1, c + h):.1f})"


def load(questions: str = "packsense_faq_test_questions.txt", labels_file: str = "external_labels.psv") -> list[dict]:
    lines = [ln for ln in (HERE / questions).read_text(encoding="utf-8").splitlines() if ln.strip()]
    labels = {}
    for ln in (HERE / labels_file).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            i, kind, prev, acc, rule = ln.split("|")
            labels[int(i)] = {"kind": kind, "prev": prev or None, "accept": set() if acc == "-" else set(acc.split(",")), "primary": None if acc == "-" else acc.split(",")[0], "rule": rule}
    rows = []
    for i, ln in enumerate(lines, 1):
        kind, text = [x.strip() for x in ln.split("|", 1)]
        lab = labels[i]
        assert lab["kind"] == kind, (i, kind, lab["kind"])
        rows.append({"n": i, "text": text.split("||")[-1].strip(), "first": text.split("||")[0].strip(), **lab})
    return rows


def new_stats() -> dict:
    return {"n": 0, "top3": 0, "top1": 0, "direct": 0, "ok": 0, "wrong": 0, "memory_off_ok": 0}


def score(m, rows: list[dict], follow: dict, loo: bool = False, memory_baseline: bool = True) -> tuple[dict, list]:
    """Per question type: counts. `loo` takes the question's own wording out of the catalogue first (needed when it was added as a training phrasing)."""
    def ok_entry(eid, accept):
        return eid is not None and any(m.canon(eid) == m.canon(x) or m.answers.get(m.canon(eid)) == m.answers.get(m.canon(x)) for x in accept)

    stats: dict[str, dict] = {}
    bad: list[tuple] = []
    for r in rows:
        if r["rule"] == "skip":                                   # a question that repeats one already seen: not scored
            continue
        bucket = r["kind"]
        s = stats.setdefault(bucket, new_stats())
        skip = r["text"] if loo else None
        res = m.match_in_context(r["text"], r["prev"], follow, "always", skip_wording=skip) if bucket == "NEXT" else m.match(r["text"], skip)
        ranked = [i for i, _ in res.ranked]
        s["n"] += 1
        if r["rule"] == "barcode":                                # a typed barcode: right when the bot sends the visitor to the lookup
            hit = res.action == "barcode"
            for k in ("top3", "top1", "direct", "ok"):
                s[k] += hit
            if not hit:
                bad.append((r["n"], bucket, "", r["text"], res.action, res.entry_id, round(res.score, 2), "miss"))
            continue
        wrong = res.action == "answer" and not ok_entry(res.entry_id, r["accept"])
        if bucket != "OFF":
            s["top3"] += any(ok_entry(i, r["accept"]) for i in ranked[:3])
            s["top1"] += bool(ranked) and ok_entry(ranked[0], r["accept"])
            direct = res.action == "answer" and ok_entry(res.entry_id, r["accept"])
            s["direct"] += direct
            good = direct or (r["rule"] == "entry_or_refuse" and res.action in REFUSALS)
        elif r["rule"] == "advice":
            good = res.action in ("advice", "medical") or (res.action == "answer" and ok_entry(res.entry_id, r["accept"]))
        else:
            good = res.action in REFUSALS or (res.action == "answer" and ok_entry(res.entry_id, r["accept"]))
        s["ok"] += good
        s["wrong"] += wrong
        if bucket == "NEXT" and memory_baseline:
            base = m.match(r["text"], skip)
            s["memory_off_ok"] += base.action == "answer" and ok_entry(base.entry_id, r["accept"])
        if not good or wrong:
            bad.append((r["n"], bucket, r["first"] if bucket == "NEXT" else "", r["text"], res.action, res.entry_id, round(res.score, 2), "WRONG" if wrong else "miss"))
    return stats, bad


def merge(stats_list: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for st in stats_list:
        for b, s in st.items():
            o = out.setdefault(b, new_stats())
            for k, v in s.items():
                o[k] += v
    return out


def report(stats: dict, title: str = "") -> None:
    if title:
        print(title)
    tot_n = sum(s["n"] for s in stats.values())
    tot_wrong = sum(s["wrong"] for s in stats.values())
    for b in ("ON", "OFF", "NEXT"):
        s = stats[b]
        n = s["n"]
        if b == "OFF":
            print(f"  OFF ({n}): handled {wilson(s['ok'], n)}; wrongly answered {s['wrong']}")
        else:
            print(f"  {b} ({n}): top-3 {wilson(s['top3'], n)}  top-1 {wilson(s['top1'], n)}  answered directly & right {wilson(s['direct'], n)}  wrong confident {s['wrong']}"
                  + (f"  | without memory: {s['memory_off_ok']} answered directly & right" if b == "NEXT" else ""))
    on, nx = stats["ON"], stats["NEXT"]
    print(f"  ALL ({tot_n}): wrong confident {wilson(tot_wrong, tot_n)}; ON+NEXT top-3 {wilson(on['top3'] + nx['top3'], on['n'] + nx['n'])}; "
          f"ON+NEXT top-1 {wilson(on['top1'] + nx['top1'], on['n'] + nx['n'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hybrid", type=float, default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    if a.hybrid is None:
        m = mt.Matcher(entries, fixed)
        mt.CONFIDENT, mt.MARGIN, mt.STRONG = 0.40, 0.10, 0.55
    else:
        import trial_embeddings as te
        m = te.HybridMatcher("sentence-transformers/all-MiniLM-L6-v2", a.hybrid, entries, fixed)
        mt.CONFIDENT, mt.MARGIN, mt.STRONG = 0.60, 0.06, 0.75
    mt.LAMBDA, mt.BETA = 0.4, 0.1
    stats, bad = score(m, load(), follow)
    report(stats)
    if not a.quiet:
        for x in bad:
            print("  ", x)


if __name__ == "__main__":
    main()
