"""Item 15 (version 2): the template story, the baseline the narrator has to beat (design 7.9 and A46). Code only: sentences filled in from the same facts, no model.

It is built to be readable, not to be a strawman: the lead is the most important finding (a pattern, then a conclusion code reached, then the largest clear change), each finding is one
sentence taken from the same derived facts the narrator gets, and the steady measures close the note in one sentence. If the owner prefers it to the model's story on most days,
the model adds nothing and the narrator is not built.
"""
from __future__ import annotations

import story_facts as sf


def _cap(s: str) -> str:
    return s[0].upper() + s[1:]


def sentences(request: dict) -> list[dict]:
    items = sf.all_items(request)
    india = request["scope"] == "india"
    out: list[dict] = []
    used: set[str] = set()

    def add(text: str, typ: str, *cites: str):
        out.append({"text": text, "type": typ, "cites": list(cites)})
        used.update(cites)

    covered = {c for p in request["patterns"] for c in p.get("cites", [])}
    for eid in request["events"]:
        it = items[eid]
        if it["kind"] == "pattern":
            if it["pattern"] == "regional_burst":
                f = items[it["cites"][0]]
                add(f"India had {f['value']} products with at least one change, {f['times_usual']} times the usual {f['usual']}, {it['wording']}.", "pattern", eid, f["id"])
            elif it["pattern"] == "wide_coverage_jump":
                add(f"{it['fields_with_a_jump']} fields were filled more often than usual in that day's file, {it['wording']}.", "pattern", eid)
            else:
                add(f"The {it['label']} were dropped for {it['dropped_per_100']} of every 100 products, against a usual {it['usual_range_per_100']}, {it['wording']}.", "pattern", eid)
        elif it["kind"] == "derived":
            add(f"{it['statement']} In short, {it['conclusion_wording']}.", "derived", eid)
        else:
            word = "higher" if it["direction"] == "up" else "lower"
            line = f"{_cap(it['label'])}: {it['value']}, {word} than the usual {it['usual']}"
            if "times_usual" in it:
                line += f" ({it['times_usual']} times)"
            if "rank_phrase" in it:
                line += f", {it['rank_phrase']}"
            if eid not in used:
                add(line + ".", "fact", eid)
            if eid not in covered:
                add(f"The change in {it['label']} is not explained by any known pattern.", "unexplained", eid)
    for d in request["derived"]:
        if d["id"] in used or d["derived"] == "steady_summary":
            continue
        if d["derived"] == "flag_bridge" or d["direction"] != "usual":
            add(d["statement"], "derived", d["id"])
    steady = [d for d in request["derived"] if d["derived"] == "steady_summary"]
    if steady:
        add(steady[0]["statement"], "derived", steady[0]["id"])
    while len(out) > 7:                                  # keep the note short: drop the last middle sentence (a share or split) before the steady summary
        drop = max(i for i, s in enumerate(out[:-1]) if s["type"] == "derived") if any(s["type"] == "derived" for s in out[:-1]) else len(out) - 2
        out.pop(drop)
    if out:
        first = out[0]["text"]
        lead = f"On {request['date_words']}, " + ("in India, " if india and not first.startswith(("India", "In India")) else "")
        out[0]["text"] = lead + (first if first.startswith(("India", "In India")) else first[0].lower() + first[1:])
    return out
