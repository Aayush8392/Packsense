"""Item 15 (version 3): the code-planned story. No model. Approved 2026-10-25: simple words, short connected sentences, every sentence a frame that code fills and checks.

A story is a plan, not a list: an opening that says what kind of day it was, then the findings in a fixed order (market share, the rest of the world, who the change belongs to, what the changes were,
the open flags), each tied to the one before it with a connecting word that code only writes when the numbers back the relation:
  'but'      the total is about the usual and the mix is not (a total and a share that differ);
  'although' a share of one thing differs from a share of another (India's part of a change type against its part of all changed products);
  'also'     a second part moved in the same direction as the first (outside India, as in India);
  'so ... not all of it' / 'so the rise is in India'  arithmetic on the parts: India's change against the rest's.
Nothing here says why anything happened. The output is the same list of sentences (text, type, cites) the checker reads, so the same rules apply to it.
"""
from __future__ import annotations

AMOUNT = {"usual": "about the usual number", "up": "more than usual", "down": "fewer than usual", "up_slight": "a little more than usual", "down_slight": "a little fewer than usual"}
SHARE_WORD = {"up": "more than", "down": "less than", "up_slight": "a little more than", "down_slight": "a little less than"}
CHANGE_NAME = {"nutrition_products": "a nutrition change", "ingredients_products": "an ingredients change"}
EVENT_NAME = {"nutrition_products": "Nutrition changes", "ingredients_products": "Ingredients changes", "new_products": "New products", "unseen_edits": "Unseen edits"}


def _moved_up(request: dict, sentence: dict) -> bool:
    """True when the sentence before rests on something that is above its usual (so 'also higher' is a true relation)."""
    items = {x["id"]: x for x in request["facts"] + request["patterns"] + request["derived"]}
    return any(items[c].get("direction") in ("up", "up_slight") for c in sentence["cites"] if c in items)


def plan(request: dict) -> list[dict]:
    facts = {f["column"]: f for f in request["facts"]}
    derived: dict[str, list[dict]] = {}
    for d in request["derived"]:
        derived.setdefault(d["derived"], []).append(d)
    patterns = {p["pattern"]: p for p in request["patterns"]}
    india = request["scope"] == "india"
    date = request["date_words"]
    out: list[dict] = []

    def say(text: str, typ: str, *cites: str):
        out.append({"text": text, "type": typ, "cites": [c for c in dict.fromkeys(cites) if c]})

    total = facts["any_products"]
    new_and_existing = (derived.get("new_and_existing") or [None])[0]
    shares = derived.get("share_of_changed", [])
    part = (derived.get("part_of_whole") or [None])[0]
    contrast = (derived.get("rest_contrast") or [None])[0]
    rest = (derived.get("india_and_rest") or [None])[0]
    bridge = (derived.get("flag_bridge") or [None])[0]
    india_share = facts.get("india_share")
    mix_event = bool(part or contrast or (india_share and india_share["direction"] in ("up", "down")) or (rest and rest.get("conclusion")))
    nothing_moved = not request["events"] and not mix_event and all(s["direction"].endswith("_slight") for s in shares)
    where = " in India" if india else ""
    # events on single measures that no other sentence will carry (they are told next to the opening or joined to the sentence before)
    loose_events = [f for f in request["facts"] if f["direction"] in ("up", "down") and f["column"] in EVENT_NAME and f["column"] not in ("new_products", "unseen_edits")]
    told_inline = False
    support_cites: list[str] = []
    inline_support = ""
    if new_and_existing and new_and_existing["direction"] != "usual" and "usual_existing" in new_and_existing and not (part or contrast):
        bits = [f"{new_and_existing['existing_n']} were existing products that were edited, {SHARE_WORD[new_and_existing['direction']]} the usual {new_and_existing['usual_existing']}"]
        support_cites += [new_and_existing["id"]]
        if shares:
            top0 = max(shares, key=lambda s: abs(s["share"] - float(s["usual"].rstrip("%")) / 100))
            bits.append(f"{top0['value_whole']} had {CHANGE_NAME[top0['sig']]}, against a usual {top0['usual_whole']}")
            support_cites += [top0["id"], *top0["cites"]]
        inline_support = ", and ".join(bits)

    # 1. the opening: what kind of day it was
    if "regional_burst" in patterns:
        rank = f", and {total['rank_phrase']}" if "rank_phrase" in total else ""
        say(f"On {date}, {total['value']} products changed in India, {total.get('times_usual', '')} times the usual {total['usual']}{rank}.", "fact", total["id"])
        say(f"This is {patterns['regional_burst']['wording']}.", "pattern", patterns["regional_burst"]["id"])
    elif total["direction"] != "usual":
        more = "more" if "up" in total["direction"] else "fewer"
        prefix = "somewhat " if "slight" in total["direction"] else ""
        say(f"On {date}, {prefix}{more} products changed{where} than usual ({total['value']}, against {total['usual']}).", "fact", total["id"])
    elif nothing_moved:
        if india:
            say(f"On {date}, nothing moved clearly in India. {total['value']} products changed there, about the usual {total['usual']}.", "fact", total["id"])
        else:
            tail = f", and India's share of them ({india_share['value']}) was about the usual too" if india_share and india_share["direction"] == "usual" else ""
            say(f"On {date}, nothing moved clearly. {total['value']} products changed, about the usual {total['usual']}{tail}.", "fact", total["id"], india_share["id"] if tail else None)
    elif mix_event or (shares and inline_support):
        say(f"On {date}, about the usual number of products changed{where} ({total['value']}), but the mix was different.", "fact", total["id"])
        if inline_support and not mix_event:
            say(f"Of them, {inline_support}.", "derived", *support_cites)
            told_inline = True
    elif loose_events:
        names = " and ".join(f"{EVENT_NAME[f['column']].lower()} ({f['value']}, against {f['usual']})" for f in loose_events)
        word = "higher than usual" if all(f["direction"] == "up" for f in loose_events) else "lower than usual" if all(f["direction"] == "down" for f in loose_events) else "away from the usual"
        say(f"On {date}, about the usual number of products changed{where} ({total['value']}), but {names} were {word}.", "fact", total["id"], *[f["id"] for f in loose_events])
    else:
        say(f"On {date}, the number of changed products{where} was about the usual ({total['value']}).", "fact", total["id"])
    for name in ("wide_coverage_jump", "tag_failure_spike"):
        if name in patterns:
            say(patterns[name]["statement"], "pattern", patterns[name]["id"])

    # 2. India's share, and the rest of the world
    if india_share and india_share["direction"] in ("up", "down"):
        only = "only " if india_share["direction"] == "down" else ""
        say(f"India had {only}{india_share['value']} of the changes, when it usually has {india_share['usual']}.", "fact", india_share["id"])
    if rest and not india and ((india_share and india_share["direction"] in ("up", "down")) or rest.get("conclusion")):
        tail = "" if rest["rest_direction"] == "usual" else f" (against {rest['rest_usual']})"
        say(f"Outside India, {rest['rest_value']} products changed, {AMOUNT[rest['rest_direction']]}{tail}.", "derived", rest["id"])
        if rest.get("conclusion"):
            say(f"This means that {rest['conclusion_wording']}.", "derived", rest["id"])

    # 3. who the change belongs to
    if part:
        over = [p for p in part["parts"] if p["relation"] == "over"]
        if over:
            only = "only " if float(part["base_pct"].rstrip("%")) < 25 else ""
            text = "India made up " + " and ".join(f"{p['pct']} of the {p['label']}" for p in over) + f", although it had {only}{part['base_pct']} of all changed products."
        else:
            text = f"India made up only {part['parts'][0]['pct']} of the {part['parts'][0]['label']}, although it had {part['base_pct']} of all changed products."
        say(text, "derived", part["id"], *part["cites"])
    if contrast:
        for kind in dict.fromkeys(e["kind"] for e in contrast["entries"]):
            group = [e for e in contrast["entries"] if e["kind"] == kind]
            if not group:
                continue
            names = " and ".join(f"{e['label']} ({e['rest_value']}, against {e['rest_usual']})" for e in group)
            if kind == "part_not_all":
                say(f"Outside India, {names} were also higher than usual, so India explains part of the rise, not all of it.", "derived", contrast["id"], *contrast["cites"])
            else:
                say(f"Outside India, {names} were about the usual, so the rise is in India.", "derived", contrast["id"], *contrast["cites"])

    # 4. what the changes were
    told_makeup = False
    if new_and_existing and new_and_existing["direction"] == "up" and shares:
        top = max(shares, key=lambda s: s["share"])
        word = "Almost all of them" if new_and_existing["existing_share"] >= 0.9 else "Most of them" if new_and_existing["existing_share"] >= 0.6 else None
        lead = f"{word} ({new_and_existing['existing_n']} of {new_and_existing['any_n']}) were existing products that were edited" if word else f"{new_and_existing['existing_n']} of them were existing products that were edited"
        say(f"{lead}, and {top['value_whole']} had {CHANGE_NAME[top['sig']]}, against a usual {top['usual_whole']}.", "derived", new_and_existing["id"], top["id"], *top["cites"])
        told_makeup = True
    elif shares and not part and not told_inline:
        top = max(shares, key=lambda s: abs(s["share"] - float(s["usual"].rstrip("%")) / 100))
        say(f"The mix differs a little: {top['value_whole']} of changed products had {CHANGE_NAME[top['sig']]}, {SHARE_WORD[top['direction']]} the usual {top['usual_whole']}.", "derived", top["id"], *top["cites"])
    cited = {c for s in out for c in s["cites"]}
    rest_events = [f for f in request["facts"] if f["direction"] in ("up", "down") and f["id"] not in cited and f["column"] in EVENT_NAME]
    if rest_events:
        names = " and ".join(f"{EVENT_NAME[f['column']].lower()} ({f['value']}, against {f['usual']})" for f in rest_events)
        names = names[0].upper() + names[1:]
        word = "higher than usual" if all(f["direction"] == "up" for f in rest_events) else "lower than usual" if all(f["direction"] == "down" for f in rest_events) else "away from the usual"
        also = "also " if out and _moved_up(request, out[-1]) and word == "higher than usual" else ""
        lead = "" if also or not out else "Separately, "
        names = names if not lead else names[0].lower() + names[1:]
        say(f"{lead}{names} were {also}{word}.", "fact", *[f["id"] for f in rest_events])
    if told_makeup and facts.get("new_products", {}).get("direction") == "usual":
        say("The number of new products stayed about the usual.", "fact", facts["new_products"]["id"])

    # 5. the open flags
    if bridge and (bridge.get("conclusion") or bridge["direction"] in ("up", "down")):
        verb = "up" if bridge["sign"] == "up" else "down"
        lead = "In India, open flags" if india else "Open flags"
        say(f"{lead} went {verb} by {bridge['delta_abs']}.", "derived", bridge["id"])
        if bridge.get("conclusion"):
            say(f"{bridge['conclusion_wording'][0].upper() + bridge['conclusion_wording'][1:]}.", "derived", bridge["id"])
        elif bridge["opened_share_of_new"] >= 0.6:
            say(f"Most of the new flags opened on products that were already known ({bridge['opened_known']} of {bridge['new_flags']}).", "derived", bridge["id"])
    return out
