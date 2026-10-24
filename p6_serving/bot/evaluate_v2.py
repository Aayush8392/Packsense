"""Scoring for the bot with hub answers and "did you mean" replies (rules written and frozen before the first run; see FROZEN_V2.txt).

What the visitor sees decides how a question is scored:
  direct answer   right when it is an accepted entry; otherwise a wrong confident answer
  hub answer      right when the question's accepted entries lie inside the hub's family (the hub has a line on each detail); otherwise a wrong confident answer
  did you mean    two buttons, no answer yet: a hit when either button is an accepted entry, a "misleading pair" when neither is (not a confident answer)
  three closest   a hit under rule A when one of the three is an accepted entry; under rule B when two are (or all that exist, when fewer than two accepted answers exist)
  decline         right for off-topic questions
A pair or a list counts as reaching the answer on the assumption that the visitor then clicks the right entry (an optimistic assumption, stated wherever numbers are quoted).

Measures (ON and follow-up questions together unless said otherwise):
  reach A / reach B   the accepted entry is within what is shown, with list rule A / B
  first screen        a correct direct answer or a hub that covers the question, with no choice needed
  strict first        the same, but a hub counts only when the hub itself is an accepted entry
  top-1 (ranking)     the old measure: the best-ranked entry is accepted
  declines            off-topic questions handled (a hub or a pair for an off-topic question is a failure)
  wrong confident     wrong direct answers plus wrong hub answers, over all questions
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_external as ee  # noqa: E402

KEYS = ["n", "direct_ok", "hub_ok", "hub_exact", "hub_wrong", "wrong_direct", "pair_ok", "pair_miss", "list_n", "reachA", "reachB", "first", "strict", "top1", "decl_ok", "used_direct", "used_hub", "used_pair", "used_list"]


def blank() -> dict:
    return {k: 0 for k in KEYS}


def score(m, rows: list[dict], follow: dict, loo: bool = False) -> tuple[dict, list]:
    stats = {"ON": blank(), "OFF": blank(), "NEXT": blank()}
    bad: list = []
    members = [{f["hub"], *f["details"]} for f in m.families]
    hubs = {f["hub"] for f in m.families}

    def ok_entry(eid, accept):
        return eid is not None and any(m.canon(eid) == m.canon(x) or m.answers.get(m.canon(eid)) == m.answers.get(m.canon(x)) for x in accept)

    for r in rows:
        if r["rule"] == "skip":
            continue
        s = stats[r["kind"]]
        skip = r["text"] if loo else None
        res = m.match_in_context(r["text"], r["prev"], follow, "always", skip_wording=skip) if r["kind"] == "NEXT" else m.match(r["text"], skip)
        accept = r["accept"]
        s["n"] += 1
        acc_canon = {m.canon(x) for x in accept}
        accepted_answers = {m.answers[m.canon(x)] for x in accept if m.canon(x) in m.answers}
        ranked = [i for i, _ in res.ranked]
        if r["kind"] != "OFF":
            s["top1"] += bool(ranked) and ok_entry(ranked[0], accept)
        if r["rule"] == "barcode":
            hit = res.action == "barcode"
            for k in ("direct_ok", "reachA", "reachB", "first", "strict", "top1", "used_direct"):
                s[k] += hit
            continue
        if res.action == "answer" and res.entry_id in hubs:       # a hub entry answered directly is a hub answer: it covers its family
            res = type(res)("hub", res.entry_id, res.score, res.ranked, res.options)
        if res.action == "answer":
            s["used_direct"] += 1
            if ok_entry(res.entry_id, accept):
                for k in ("direct_ok", "reachA", "reachB", "first", "strict", "decl_ok"):
                    s[k] += 1
            else:
                s["wrong_direct"] += 1
                bad.append((r["n"], r["kind"], r["text"], "WRONG direct", res.entry_id))
        elif res.action == "hub":
            s["used_hub"] += 1
            fam = next(mem for mem in members if res.entry_id in mem)
            covers = bool(acc_canon & fam)
            if covers:
                s["hub_ok"] += 1
                s["hub_exact"] += res.entry_id in acc_canon
                for k in ("reachA", "reachB", "first", "decl_ok"):
                    s[k] += 1
                s["strict"] += res.entry_id in acc_canon
            else:
                s["hub_wrong"] += 1
                bad.append((r["n"], r["kind"], r["text"], "WRONG hub", res.entry_id))
        elif res.action == "choice":
            s["used_pair"] += 1
            if any(ok_entry(o, accept) for o in res.options):
                s["pair_ok"] += 1
                s["reachA"] += 1
                s["reachB"] += 1
            else:
                s["pair_miss"] += 1
                bad.append((r["n"], r["kind"], r["text"], "misleading pair", res.options))
        else:
            if res.action in ("generic",):
                s["used_list"] += 1
            top3 = ranked[:3]
            hits = len({m.answers[m.canon(i)] for i in top3 if ok_entry(i, accept)})
            if r["kind"] != "OFF":
                s["list_n"] += 1
                got_a, got_b = hits >= 1, hits >= min(2, max(1, len(accepted_answers)))
                if r["rule"] == "entry_or_refuse" and res.action in ee.REFUSALS:                       # a decline is an acceptable outcome for these questions (rule corrected after round 4)
                    got_a = got_b = True
                s["reachA"] += got_a
                s["reachB"] += got_b
            if r["kind"] == "OFF":
                good = res.action in ee.REFUSALS if r["rule"] != "advice" else res.action in ("advice", "medical")
                s["decl_ok"] += good
            if r["kind"] != "OFF" and r["rule"] == "entry_or_refuse" and res.action in ee.REFUSALS:
                s["decl_ok"] += 1
    return stats, bad


def merge(parts: list[dict]) -> dict:
    out = {k: blank() for k in ("ON", "OFF", "NEXT")}
    for p in parts:
        for kind, s in p.items():
            for k, v in s.items():
                out[kind][k] += v
    return out


def wilson(k: int, n: int) -> str:
    return ee.wilson(k, n)


def report(stats: dict, title: str = "") -> None:
    on, nx, off = stats["ON"], stats["NEXT"], stats["OFF"]
    n = on["n"] + nx["n"]
    tot = lambda k: on[k] + nx[k]
    total_n = on["n"] + nx["n"] + off["n"]
    wrong = on["wrong_direct"] + on["hub_wrong"] + nx["wrong_direct"] + nx["hub_wrong"] + off["wrong_direct"] + off["hub_wrong"]
    if title:
        print(title)
    print(f"  reach A (list needs 1 right): {wilson(tot('reachA'), n)}")
    print(f"  reach B (list needs 2 right): {wilson(tot('reachB'), n)}")
    print(f"  first screen (direct right or hub covers): {wilson(tot('first'), n)}   strict (hub must itself be accepted): {wilson(tot('strict'), n)}   old top-1 ranking: {wilson(tot('top1'), n)}")
    print(f"  what was shown (ON+NEXT, {n}): direct {tot('used_direct')}, hub {tot('used_hub')}, did-you-mean {tot('used_pair')}, three closest {tot('used_list')}  "
          f"| hub right {tot('hub_ok')}, hub wrong {tot('hub_wrong')}, pair hit {tot('pair_ok')}, misleading pair {tot('pair_miss')}")
    print(f"  declines handled (OFF {off['n']}): {wilson(off['decl_ok'], off['n'])}; OFF answered by direct/hub: {off['used_direct'] + off['used_hub']}, pair: {off['used_pair']}")
    print(f"  wrong confident (all {total_n}): {wilson(wrong, total_n)}  [direct {tot('wrong_direct') + off['wrong_direct']}, hub {tot('hub_wrong') + off['hub_wrong']}]")
