"""Measure the follow-up memory on the two-turn chats (Phase C item 14): chats.psv holds the first answer (an entry id), the follow-up typed, and the right entry.

  python p6_serving/bot/evaluate_chats.py                      # keywords only
  <scratch venv>/Scripts/python.exe p6_serving/bot/evaluate_chats.py --hybrid 0.7   # keywords blended with the embedding model

The base chats (ids without "-r") are used to tune the two weights; the variants (with "-r") are then a check on phrasings that were not used to tune.
"harm" counts a topic switch or follow-up that the plain matcher got right and the memory got wrong.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import matcher as mt  # noqa: E402


def load_chats() -> list[dict]:
    rows = []
    for line in (HERE / "chats.psv").read_text(encoding="utf-8").splitlines():
        if line.strip():
            cid, prev, text, want, kind = line.split("|")
            rows.append({"id": cid, "prev": prev, "text": text, "want": want, "kind": kind, "variant": "-r" in cid})
    return rows


def score(m, chats, follow, mode, ref=None):
    out = {"follow": 0, "top1": 0, "top3": 0, "direct": 0, "wrong": 0, "switch": 0, "switch_ok": 0, "harm": 0, "lost": 0}
    same = lambda a, b: m.canon(a) == m.canon(b) or m.answers.get(m.canon(a)) == m.answers.get(m.canon(b))               # noqa: E731
    for c in chats:
        r = m.match_in_context(c["text"], c["prev"], follow, mode)
        ranked = [i for i, _ in r.ranked]
        right = r.action == "answer" and same(r.entry_id, c["want"])
        if c["kind"] == "followup":
            out["follow"] += 1
            out["top1"] += bool(ranked) and same(ranked[0], c["want"])
            out["top3"] += any(same(i, c["want"]) for i in ranked[:3])
            out["direct"] += right
            out["wrong"] += r.action == "answer" and not right
        else:
            out["switch"] += 1
            out["switch_ok"] += right
            out["wrong"] += r.action == "answer" and not right
        if ref is not None and ref[c["id"]] and not right:
            out["harm" if r.action == "answer" else "lost"] += 1        # harm: memory turned a right answer into a wrong one; lost: it turned it into "here are the three closest"
    return out


def line(label, o):
    f, s = o["follow"], o["switch"]
    return (f"{label}: follow-ups {f}: top-3 {100 * o['top3'] / f:.1f}%  top-1 {100 * o['top1'] / f:.1f}%  answered directly & right {100 * o['direct'] / f:.1f}% | "
            f"switches {s}: right {o['switch_ok']}/{s} | wrong confident answers {o['wrong']} | made worse by memory {o['harm']} (lost the direct answer: {o['lost']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hybrid", type=float, default=None, help="blend weight of the embedding model (needs sentence-transformers)")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    a = ap.parse_args()
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    if a.hybrid is None:
        m = mt.Matcher(entries, fixed)
        mt.CONFIDENT, mt.MARGIN, mt.STRONG = 0.40, 0.10, 0.55
    else:
        import trial_embeddings as te
        m = te.HybridMatcher(a.model, a.hybrid, entries, fixed)
        mt.CONFIDENT, mt.MARGIN, mt.STRONG = 0.60, 0.06, 0.75
    chats = load_chats()
    base = [c for c in chats if not c["variant"]]
    var = [c for c in chats if c["variant"]]
    ref = {c["id"]: (lambda r: r.action == "answer" and m.canon(r.entry_id) == m.canon(c["want"]))(m.match_in_context(c["text"], c["prev"], follow, "off")) for c in chats}
    print(line("no memory, base chats ", score(m, base, follow, "off")))
    print(line("no memory, variants   ", score(m, var, follow, "off")))
    best = None
    for lam in (0.0, 0.1, 0.2, 0.3, 0.4, 0.6):
        for beta in (0.0, 0.05, 0.1, 0.2):
            for mode in ("weak", "always"):
                mt.LAMBDA, mt.BETA = lam, beta
                o = score(m, base, follow, mode, ref)
                key = (o["wrong"] + o["harm"], -o["top3"], -o["top1"], -o["direct"])
                if best is None or key < best[0]:
                    best = (key, lam, beta, mode, o)
    _, lam, beta, mode, o = best
    mt.LAMBDA, mt.BETA = lam, beta
    print(f"chosen on the base chats: lambda {lam} beta {beta} mode {mode}")
    print(line("memory, base chats    ", o))
    print(line("memory, variants      ", score(m, var, follow, mode, ref)))


if __name__ == "__main__":
    main()
