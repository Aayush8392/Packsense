"""Pooled leave-one-source-out test of the long-message variants (segment.py).

    PACKSENSE_LABELS=union <scratch venv>/Scripts/python.exe p6_serving/bot/pooled_seg.py <none|last|qmax|allmax>

Each held-out source is tested twice: as written, and with a story wrapped around every message ("padded"), which makes long messages from questions whose labels are known.
The padding uses generic preambles and closings written here; no question of the fresh Qwen set was used.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import cross_validate as cv  # noqa: E402
import evaluate_v2 as ev  # noqa: E402
import pooled_cv as pc  # noqa: E402
import segment_matcher as sg  # noqa: E402

PRE = ["Hi there, I have been looking around the site for a while and I wanted to ask something: ",
       "So basically I run a small business in Pune and a colleague pointed me to this website, and my question is ",
       "um so i was reading through your pages last night and i just wanna know ",
       "Good afternoon, I am a student working on a project about packaged food and I have a quick question, ",
       "I am a bit confused and worried about something, so can you tell me ",
       "Hello, I have been using food data for a couple of years and only just found this site, and I would like to understand ",
       "My manager asked me to look into this and I am not very technical, so please explain ",
       "I spent about twenty minutes on your site and could not find it, so ",
       "Sorry if this is a silly question, I am new here and a friend sent me the link. ",
       "I am writing a short article and need to get my facts straight before I publish. ",
       "ok so my cousin told me about this site and said to just ask, so "]
POST = [" Thanks in advance for your help.", " I would really appreciate a straight answer today.", " I have been trying to figure this out for a week.",
        " Please keep it simple, I am not an expert.", " Sorry for the long message.", " Let me know whenever you can."]


def pad(text: str, n: int) -> str:
    h = int(hashlib.sha256(f"pad:{n}".encode()).hexdigest(), 16)
    pre, post = PRE[h % len(PRE)], POST[(h // 7) % len(POST)]
    style = (h // 101) % 10
    body = text[0].lower() + text[1:] if pre.rstrip().endswith((",", ":", "so", "know", "tell me", "explain")) or pre.endswith(" ") else text
    if style < 4:
        return pre + body
    if style < 7:
        return pre + body + post
    return body + post if style < 9 else pre + body


def padded(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r["rule"] in ("skip", "barcode") or not r["text"].strip():
            continue
        out.append({**r, "text": pad(r["text"], r["n"])})
    return out


def run(variant: str, rows, entries, fixed, follow):
    import trial_embeddings  # noqa: F401
    per_orig, per_pad, chosen = [], [], []
    for train, test in pc.splits(rows, "loso"):
        m = sg.SegmentMatcher(cv.MODEL, 0.7, cv.with_extra_wordings(entries, train), fixed)
        m.variant = "none"
        tr = [r for r in train if r["rule"] != "skip"]
        best = None
        for p in pc.GRID:                                              # thresholds are tuned on the unpadded training questions, as in production
            cv.set_params(m, p)
            st, _ = ev.score(m, tr, follow, loo=True)
            key = (pc.objective(st), -abs(p[1] - 0.6))
            if best is None or key > best[0]:
                best = (key, p)
        cv.set_params(m, best[1])
        m.variant = variant
        per_orig.append(ev.score(m, test, follow)[0])
        per_pad.append(ev.score(m, padded(test), follow)[0])
        chosen.append(best[1])
    return ev.merge(per_orig), ev.merge(per_pad), chosen


def main() -> None:
    variant = sys.argv[1]
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    rows = pc.load_pool()
    so, sp, chosen = run(variant, rows, entries, fixed, follow)
    print(f"{variant:7s} as written  {pc.line(so)}")
    print(f"{variant:7s} padded      {pc.line(sp)}\n{'':16s}settings {chosen}", flush=True)


if __name__ == "__main__":
    main()
