"""Measure the matcher on the question sets (Phase C item 14).

  python p6_serving/bot/evaluate_matcher.py                 # working set, leave-one-out (the default; use this while tuning)
  python p6_serving/bot/evaluate_matcher.py --set heldout --final   # the single final run on the held-out set

Leave-one-out: while a working question is tested, its own wording is taken out of the catalogue, so the matcher has to find the answer from the
other wordings and the answer text. Without that, every working question would match itself and the score would mean nothing.
The held-out set is refused unless --final is given, so it cannot be read by accident while tuning.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import matcher as mt  # noqa: E402
import split_questions as sq  # noqa: E402

REFUSALS = {"generic", "advice", "medical", "time", "ranking", "productfacts", "meta"}        # every kind of "not answerable" reply the bot has
EXPECTED = {"Advice": {"advice", "medical"}, "Health": {"advice", "medical"}, "Medical": {"advice", "medical"}, "NotEnglish": {"english_only"}, "Barcode": {"barcode"},
            "NearMiss": REFUSALS | {"barcode"}}
FILL = {"{product}": "Maggi noodles", "{brand}": "Amul", "{barcode}": "8901719135170"}      # a visitor types a real name, not a placeholder


def fill(text: str) -> str:
    for k, v in FILL.items():
        text = text.replace(k, v)
    return text


# Fixed BEFORE the held-out run (2026-10-24): for some decline groups a catalogue entry IS the right reply, so answering with it is correct, not a wrong answer.
ACCEPT = {"Technical": {"3.13", "1.16"}, "Project": {"1.15", "1.16"}, "ProductFacts": {"7.4", "7.5"}, "NearMiss": {"7.4", "7.5", "10.15"}}


def truth_for(rows, entries, covers):
    index, alias, ids = {}, {e["id"]: e["same_as"] for e in entries if e.get("same_as")}, {e["id"] for e in entries}
    for e in entries:
        for w in cat.wordings(e):
            index.setdefault(cat.normalise(w), e.get("same_as") or e["id"])        # a same_as entry is answered by its target
    out = {}
    for r in rows:
        base = r["id"].split("-r")[0] if "-r" in r["id"] else r["id"]
        hit = covers.get(base) or (base if base in ids else None)
        out[r["id"]] = alias.get(hit, hit) if hit else index.get(cat.normalise(r["text"]))
    return out


def run(rows, m, truth, loo=True):
    same = lambda a, b: m.canon(a) == m.canon(b) or m.answers.get(m.canon(a)) == m.answers.get(m.canon(b))                  # noqa: E731  entries with the same answer text are the same answer
    answerable = [r for r in rows if not r["kind"].startswith("Decline")]
    declines = [r for r in rows if r["kind"].startswith("Decline")]
    res = {"n_ans": len(answerable), "n_dec": len(declines), "top1": 0, "top3": 0, "direct": 0, "wrong_conf": 0, "misrouted": 0, "dec_ok": 0, "dec_wrong_answer": 0}
    misses, bad_dec = [], []
    for r in answerable:
        q = fill(r["text"])
        out = m.match(q, skip_wording=r["text"] if loo else None)
        t = truth[r["id"]]
        ranked = [i for i, _ in (out.ranked or m.scores(q, r["text"] if loo else None)[:3])]
        res["top1"] += same(ranked[0], t)
        res["top3"] += any(same(i, t) for i in ranked[:3])
        if out.action == "answer":
            if same(out.entry_id, t):
                res["direct"] += 1
            else:
                res["wrong_conf"] += 1
                misses.append((r["id"], r["text"], "WRONG ANSWER", out.entry_id, round(out.score, 2)))
        elif out.action != "generic":
            res["misrouted"] += 1
            misses.append((r["id"], r["text"], "MISROUTED", out.action, round(out.score, 2)))
        elif not any(same(i, t) for i in ranked[:3]):
            misses.append((r["id"], r["text"], "NOT IN TOP 3", ranked[:3], round(out.score, 2)))
    for r in declines:
        out = m.match(fill(r["text"]))
        group = r["kind"].split(":", 1)[1]
        want = EXPECTED.get(group, REFUSALS)
        if out.action == "answer" and out.entry_id in ACCEPT.get(group, ()):
            res["dec_ok"] += 1
        elif out.action == "answer":
            res["dec_wrong_answer"] += 1
            res["wrong_conf"] += 1
            bad_dec.append((r["id"], r["text"], "ANSWERED", out.entry_id, round(out.score, 2)))
        elif out.action in want:
            res["dec_ok"] += 1
        else:
            bad_dec.append((r["id"], r["text"], f"WANTED {sorted(want)}", out.action, round(out.score, 2)))
    return res, misses, bad_dec


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["working", "heldout"], default="working")
    ap.add_argument("--final", action="store_true", help="required for the held-out set")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--hybrid", type=float, default=None, help="blend weight of the embedding model (needs sentence-transformers)")
    ap.add_argument("--summary", action="store_true", help="print only the summary lines")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.set == "heldout" and not a.final:
        sys.exit("The held-out set is for the single final run. Add --final only when tuning is finished.")
    rows = sq.load(HERE / f"questions_{a.set}.psv")
    entries, fixed = cat.load_entries(), cat.load_fixed()
    if a.hybrid is None:
        m = mt.Matcher(entries, fixed)
    else:
        import trial_embeddings as te
        m = te.HybridMatcher("sentence-transformers/all-MiniLM-L6-v2", a.hybrid, entries, fixed)
        mt.CONFIDENT, mt.MARGIN, mt.STRONG = 0.60, 0.06, 0.75
    truth = truth_for(rows, entries, cat.COVERS)
    unknown = [r["id"] for r in rows if not r["kind"].startswith("Decline") and truth[r["id"]] is None]
    if unknown:
        sys.exit(f"No catalogue entry for: {unknown}")
    loo = a.set == "working"
    if a.set == "heldout":
        buckets = {"original questions": [r for r in rows if not r["kind"].startswith("Decline") and "-r" not in r["id"]],
                   "rewordings": [r for r in rows if "-r" in r["id"] and not r["kind"].startswith("Decline")],
                   "declines": [r for r in rows if r["kind"].startswith("Decline")]}
        for name, rs in buckets.items():
            res, misses, bad = run(rs, m, truth, loo=False)
            n, d = res["n_ans"], res["n_dec"]
            if n:
                print(f"{name} ({n}): top-3 {pct(res['top3'], n)}  top-1 {pct(res['top1'], n)}  answered directly & right {pct(res['direct'], n)}  wrong confident {res['wrong_conf']}")
            else:
                print(f"{name} ({d}): handled {pct(res['dec_ok'], d)}  wrongly answered {res['dec_wrong_answer']}")
            if not a.summary:
                for x in misses + bad:
                    print("  ", x)
        res, _, _ = run(rows, m, truth, loo=False)
        print(f"ALL ({len(rows)}): wrong confident answers {res['wrong_conf']}/{len(rows)} = {pct(res['wrong_conf'], len(rows))}; top-3 {pct(res['top3'], res['n_ans'])}; top-1 {pct(res['top1'], res['n_ans'])}; declines handled {pct(res['dec_ok'], res['n_dec'])}")
        return
    grid = [(t, g) for t in (0.3, 0.4, 0.5) for g in (0.0, 0.05, 0.1, 0.15)] if a.sweep else [(mt.CONFIDENT, mt.MARGIN)]
    for t, g in grid:
        mt.CONFIDENT, mt.MARGIN = t, g
        res, misses, bad_dec = run(rows, m, truth, loo)
        n_all = res["n_ans"] + res["n_dec"]
        print(f"threshold {t} margin {g}: top-3 {pct(res['top3'], res['n_ans'])}  top-1 {pct(res['top1'], res['n_ans'])}  answered directly & right {pct(res['direct'], res['n_ans'])}  "
              f"declines handled {pct(res['dec_ok'], res['n_dec'])}  wrong confident answers {res['wrong_conf']}/{n_all} = {pct(res['wrong_conf'], n_all)}  misrouted {res['misrouted']}")
    if a.verbose or not a.sweep:
        for x in misses + bad_dec:
            print("  ", x)


if __name__ == "__main__":
    main()
