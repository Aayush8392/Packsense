"""Pooled cross-validation of the learned answer-or-decline rule against the fixed thresholds (same splits, same scoring as pooled_cv.py).

    <scratch venv>/Scripts/python.exe p6_serving/bot/pooled_abstain.py [model]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import abstain as ab  # noqa: E402
import catalogue as cat  # noqa: E402
import cross_validate as cv  # noqa: E402
import evaluate_v2 as ev  # noqa: E402
import matcher as mt  # noqa: E402
import pooled_cv as pc  # noqa: E402

TAUS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.97, 0.99)
GATES = (0.45, 0.55, 0.65)


def instances(m, rows, follow):
    """(features, label, text) for every question whose best entry can be judged."""
    out = []
    members = [{f["hub"], *f["details"]} for f in m.families]

    def ok_entry(eid, accept):
        return any(m.canon(eid) == m.canon(x) or m.answers.get(m.canon(eid)) == m.answers.get(m.canon(x)) for x in accept)

    saved = m.w, dict(m.p_override)
    m.w, m.p_override = None, {}
    for r in rows:
        if r["rule"] == "skip":
            continue
        res = m.match_in_context(r["text"], r["prev"], follow, "always", skip_wording=r["text"]) if r["kind"] == "NEXT" else m.match(r["text"], r["text"])
        if not res.ranked:
            continue
        top_id, top = res.ranked[0]
        plain = m.scores(r["text"], r["text"])
        rival = next((s for i, s in plain if m.answers[i] != m.answers[top_id]), 0.0)
        acc = {m.canon(x) for x in r["accept"]}
        right = ok_entry(top_id, r["accept"]) or (top_id in {f["hub"] for f in m.families} and any(top_id in mem and acc & mem for mem in members))
        out.append((m.features(r["text"], top_id, top, rival), float(right), r["text"]))
    m.w, m.p_override = saved
    return out


def run(model: str, mode: str, rows, entries, fixed, follow):
    per, chosen = [], []
    for train, test in pc.splits(rows, mode):
        es = cv.with_extra_wordings(entries, train)
        m = ab.AbstainMatcher(model, 0.7, es, fixed)
        cv.set_params(m, (0.7, 0.60, 0.06))
        mt.STRONG = 0.75
        tr = [r for r in train if r["rule"] != "skip"]
        inst = instances(m, tr, follow)
        X, y, texts = np.array([i[0] for i in inst]), np.array([i[1] for i in inst]), [i[2] for i in inst]
        idx = np.arange(len(y)) % 3                                   # cross-fitted probabilities choose tau and the gate
        cross = {}
        for f in range(3):
            w, mu, sd = ab.fit(X[idx != f], y[idx != f])
            Z = (X[idx == f] - mu) / sd
            Z[:, 0] = 1.0
            for t, p in zip(np.array(texts)[idx == f], 1 / (1 + np.exp(-(Z @ w)))):
                cross[t] = float(p)
        best = None
        m.p_override = cross
        for gate in GATES:
            mt.CONFIDENT = gate
            for tau in TAUS:
                m.tau = tau
                st, _ = ev.score(m, tr, follow, loo=True)
                key = (pc.objective(st), -abs(tau - 0.7))
                if best is None or key > best[0]:
                    best = (key, tau, gate)
        m.p_override = {}
        m.w, m.mu, m.sd = ab.fit(X, y)
        m.tau, mt.CONFIDENT = best[1], best[2]
        per.append(ev.score(m, test, follow)[0])
        chosen.append((best[1], best[2]))
        mt.CONFIDENT = 0.60
    return ev.merge(per), chosen


def curve(model: str, rows, entries, fixed, follow, taus=(0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.97, 0.99), gate=0.55):
    """The trade-off: for each answer threshold, the model fitted on the training sources only, applied to the held-out source (leave-one-source-out)."""
    fits = []
    for train, test in pc.splits(rows, "loso"):
        m = ab.AbstainMatcher(model, 0.7, cv.with_extra_wordings(entries, train), fixed)
        cv.set_params(m, (0.7, 0.60, 0.06))
        mt.STRONG = 0.75
        inst = instances(m, [r for r in train if r["rule"] != "skip"], follow)
        m.w, m.mu, m.sd = ab.fit(np.array([i[0] for i in inst]), np.array([i[1] for i in inst]))
        fits.append((m, test))
    for tau in taus:
        per = []
        for m, test in fits:
            m.tau, mt.CONFIDENT = tau, gate
            per.append(ev.score(m, test, follow)[0])
        mt.CONFIDENT = 0.60
        print(f"tau {tau:.2f}  {pc.line(ev.merge(per))}", flush=True)


def main() -> None:
    if "--curve" in sys.argv:
        entries, fixed = cat.load_entries(), cat.load_fixed()
        curve("sentence-transformers/all-MiniLM-L6-v2", pc.load_pool(), entries, fixed, cat.load_follow_ups(entries))
        return
    model = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "sentence-transformers/all-MiniLM-L6-v2"
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    rows = pc.load_pool()
    for mode in ("loso", "5fold"):
        st, chosen = run(model, mode, rows, entries, fixed, follow)
        print(f"learned abstain  {mode:6s} {pc.line(st)}\n{'':24s}(tau, gate) per fold {chosen}", flush=True)


if __name__ == "__main__":
    main()
