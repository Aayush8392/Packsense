"""Pooled cross-validation over the three outside question sets (Phase C item 14), with models compared under the v2 scoring.

    <scratch venv>/Scripts/python.exe p6_serving/bot/pooled_cv.py <model name | keywords> [...]

Two evaluations per model: leave-one-source-out (train on two sets, test on the third) and 5-fold stratified over the pool.
Thresholds are chosen per model on the training part only (see FROZEN_V4.txt). Run from the scratch venv that has sentence-transformers.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("PACKSENSE_NO_SEEN_POOLED", "1")          # the pooled tests add the training sets themselves; the stored copy of the first three sets must not leak into them
sys.path.insert(0, str(HERE))
import catalogue as cat  # noqa: E402
import cross_validate as cv  # noqa: E402
import evaluate_external as ee  # noqa: E402
import evaluate_v2 as ev  # noqa: E402
import matcher as mt  # noqa: E402

SOURCES = {"first": ("packsense_faq_test_questions.txt", "external_labels.psv", 0),
           "gemini": ("fresh_questions_gemini.txt", "fresh_labels.psv", 1000),
           "perplexity": ("fresh_questions_perplexity.txt", "fresh2_labels.psv", 2000)}
GRID = [(a, t, g) for a in (0.5, 0.7, 0.85) for t in (0.5, 0.6, 0.7, 0.8) for g in (0.03, 0.06, 0.10)]
LEX_GRID = [(0.0, t, g) for t in (0.3, 0.4, 0.5, 0.6) for g in (0.05, 0.10, 0.15)]


def second_labels() -> dict[str, str]:
    """The second labeller's answers: ref (A12, B7, C101) -> "ids", "NONE" or "ADVICE"."""
    out = {}
    for ln in (HERE / "labeller" / "labels_deepseek.txt").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            ref, v = [x.strip() for x in ln.split("|", 1)]
            out[ref] = v
    return out


def relabel(r: dict, ref: str, theirs: dict[str, str], mode: str) -> dict:
    """mode "theirs": the second labeller's view of the question; "union": accepted when either labeller accepts (and a decline is allowed when either would decline)."""
    if r["rule"] in ("skip", "barcode"):
        return r
    v = theirs[ref]
    ids = set() if v in ("NONE", "ADVICE") else {x.strip() for x in v.split(",")}
    out = dict(r)
    if mode == "theirs":
        out["accept"] = ids
        out["rule"] = "entry" if ids else ("advice" if v == "ADVICE" else "refuse")
        out["kind"] = "NEXT" if r["kind"] == "NEXT" else ("ON" if ids else "OFF")
    else:
        both = r["accept"] | ids
        mine_declines = r["rule"] in ("refuse", "advice", "entry_or_refuse")
        theirs_declines = not ids
        out["accept"] = both
        if both:
            out["rule"] = "entry" if not (mine_declines or theirs_declines) else "entry_or_refuse"
            out["kind"] = "NEXT" if r["kind"] == "NEXT" else "ON"
        else:
            out["rule"] = "advice" if (r["rule"] == "advice" or v == "ADVICE") else "refuse"
            out["kind"] = "OFF"
    out["primary"] = next(iter(sorted(out["accept"], key=lambda x: (r["accept"] and x not in r["accept"], x))), None) if out["accept"] else None
    return out


def load_pool(labels: str | None = None) -> list[dict]:
    labels = labels or os.environ.get("PACKSENSE_LABELS", "mine")
    theirs = second_labels() if labels != "mine" else {}
    rows = []
    for tag, (src, (q, lab, off)) in zip("ABC", SOURCES.items()):
        for r in ee.load(q, lab):
            row = {**r, "src": src, "n": r["n"] + off}
            if labels != "mine":
                row = relabel(row, f"{tag}{r['n']}", theirs, labels)
            rows.append(row)
    return rows


def objective(st: dict) -> float:
    tot = lambda k: sum(st[x][k] for x in ("ON", "NEXT"))
    wrong = sum(st[x]["wrong_direct"] + st[x]["hub_wrong"] for x in st)
    return tot("first") + tot("reachB") - 6 * wrong - 2 * (st["OFF"]["n"] - st["OFF"]["decl_ok"])


def stratified(rows: list[dict], k: int = 5) -> list[list[dict]]:
    out = [[] for _ in range(k)]
    for kind in ("ON", "OFF", "NEXT"):
        part = sorted((r for r in rows if r["kind"] == kind), key=lambda r: hashlib.sha256(f"packsense-pool-2026:{r['n']}".encode()).hexdigest())
        for i, r in enumerate(part):
            out[i % k].append(r)
    return out


def splits(rows: list[dict], mode: str):
    if mode == "loso":
        return [([r for r in rows if r["src"] != s], [r for r in rows if r["src"] == s]) for s in SOURCES]
    fs = stratified(rows)
    return [([r for j, f in enumerate(fs) if j != i for r in f], fs[i]) for i in range(len(fs))]


def run(model: str, mode: str, rows, entries, fixed, follow):
    import trial_embeddings as te
    per, chosen = [], []
    for train, test in splits(rows, mode):
        es = cv.with_extra_wordings(entries, train)
        if model == "keywords":
            m, grid = mt.Matcher(es, fixed), LEX_GRID
        else:
            m, grid = te.HybridMatcher(model, 0.7, es, fixed), GRID
        tr = [r for r in train if r["rule"] != "skip"]
        best = None
        for p in grid:
            cv.set_params(m, p)
            st, _ = ev.score(m, tr, follow, loo=True)
            key = (objective(st), -abs(p[1] - 0.6))
            if best is None or key > best[0]:
                best = (key, p)
        cv.set_params(m, best[1])
        per.append(ev.score(m, test, follow)[0])
        chosen.append(best[1])
    return ev.merge(per), chosen


def line(st: dict) -> str:
    on, nx, off = st["ON"], st["NEXT"], st["OFF"]
    n = on["n"] + nx["n"]
    t = lambda k: on[k] + nx[k]
    wrong = sum(st[x]["wrong_direct"] + st[x]["hub_wrong"] for x in st)
    tn = n + off["n"]
    return (f"reachA {100 * t('reachA') / n:.1f}%  reachB {100 * t('reachB') / n:.1f}%  first {100 * t('first') / n:.1f}%  top1 {100 * t('top1') / n:.1f}%  "
            f"declines {100 * off['decl_ok'] / off['n']:.1f}%  wrong {100 * wrong / tn:.1f}% ({wrong}/{tn})  | direct {t('used_direct')} hub {t('used_hub')} pair {t('used_pair')} list {t('used_list')} (n={n})")


def main() -> None:
    entries, fixed = cat.load_entries(), cat.load_fixed()
    follow = cat.load_follow_ups(entries)
    rows = load_pool()
    for model in sys.argv[1:]:
        for mode in ("loso", "5fold"):
            st, chosen = run(model, mode, rows, entries, fixed, follow)
            print(f"{model:42s} {mode:6s} {line(st)}\n{'':49s}settings {chosen}", flush=True)


if __name__ == "__main__":
    main()
