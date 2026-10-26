"""Item 15, step 4a (version 2): the facts one story is allowed to use (context amendments A46 and A47). Code only, no model.

A story request is one (UTC day, scope). Code computes every fact, gives it an id, writes the comparative word ('up', 'down', 'up_slight', 'down_slight' or 'usual') and the display
forms of its numbers; the narrator may only use those. Version 2 adds DERIVED facts: conclusions that follow from arithmetic on the data, each carrying the identity it rests on
(all changed products = India + the rest; changed products = new + existing; the change in open flags = flags on newly seen products + flags opened on known products - flags ended).
Patterns (approved 2026-10-24: regional burst, wide coverage jump, tag failure spike) are matched by named rules. The caveats are appended by code after the story.
"""
from __future__ import annotations

import csv
import statistics
from datetime import date
from pathlib import Path

import story_lib as sl

LABELS = {
    "any_products": "products with at least one change",
    "new_products": "new products",
    "unseen_edits": "edits counted but not seen",
    "nutrition_products": "products with a nutrition change",
    "ingredients_products": "products with an ingredients change",
    "india_share": "India's share of changed products",
}
SHORT_NAMES = {   # the short names the closing 'not explained' sentence uses for a long label
    "any_products": "the number of changed products",
    "nutrition_products": "nutrition changes",
    "ingredients_products": "ingredients changes",
    "india_share": "India's share of changes",
}
SCOPE_SIGNALS = {"all": ("any_products", "new_products", "unseen_edits", "nutrition_products", "ingredients_products", "india_share"),
                 "india": ("any_products", "new_products", "unseen_edits", "nutrition_products", "ingredients_products")}
CAVEATS = {
    "complete_days": "Only complete days are used. A day here runs from about 06:30 UTC to 06:30 UTC.",
    "lower_bound": "Counts are a floor: edits that happened between two daily files are counted but not seen.",
    "coverage": "Outside India, only products edited since 30 September 2026 are held.",
}
SHORT_LABELS = {"any_products": "changed products", "new_products": "new products", "unseen_edits": "unseen edits", "nutrition_products": "nutrition changes",
                "ingredients_products": "ingredients changes", "india_share": "India's share"}
FOOTER = "AI-generated, unreviewed. It describes PackSense's copy of Open Food Facts data and gives no advice."
MIN_COVERAGE_WARNINGS = 5
SLIGHT_Z = 2.0
MIN_MOVE = 10                                # a move smaller than this many products is noise, whatever its ratio
INDIA_FLOOR = {"any_products": 10, "new_products": 5, "unseen_edits": 5, "nutrition_products": 5, "ingredients_products": 5}


def floor_for(scope: str, sig: str) -> float:
    """Below this level (both the day and its usual) a signal is called usual: India's counts are small, so its floors are lower than the all-markets ones."""
    return INDIA_FLOOR.get(sig, 0) if scope == "india" else sl.MIN_BASELINE[sig]

RATIO_HIGH, RATIO_LOW = 1.25, 0.8           # a spread that is wide must not hide a move of a quarter or more
MIN_COUNT_FOR_SHARES = 30                   # a share of fewer changed products than this is noise
CARRIED_SHARE_FOR_CONCLUSION = 0.9
SHARE_PARTS = {"nutrition_products": "had a nutrition change", "ingredients_products": "had an ingredients change"}


def _fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.1f}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _pct_short(x: float) -> str:
    """A share for plain reading: whole percent from 10% up, one decimal below."""
    return f"{x * 100:.0f}%" if x >= 0.095 else f"{x * 100:.1f}%"


def load_quality(path: str | Path) -> dict[str, dict[str, dict[str, float]]]:
    """scope -> day -> open_spans, opened_on_known, carried_in, vanished, products_held."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["scope"], {})[r["snapshot_date"]] = {k: float(r[k]) for k in ("open_spans", "opened_on_known", "carried_in", "vanished", "products_held")}
    return out


_STATES: dict[tuple, list] = {}


def _states(series: dict[str, float], ordered: list[str]) -> list:
    """For every day in order: (value, baseline, spread, z) or None. The baseline is the median of the days before it in the window, leaving out days that were themselves clear events (4 spreads
    or more away), so a burst does not become the 'usual' for the days after it; if fewer than MIN_HISTORY ordinary days remain, the plain window median is used (a lasting change becomes the new usual)."""
    key = (tuple(sorted(series.items())), tuple(ordered))
    if key in _STATES:
        return _STATES[key]
    out: list = []
    event: list[bool] = []
    for i, day in enumerate(ordered):
        window = [(d, k) for d, k in zip(ordered[max(0, i - sl.WINDOW):i], event[max(0, i - sl.WINDOW):i]) if d in series]
        if len(window) < sl.MIN_HISTORY or day not in series:
            out.append(None)
            event.append(False)
            continue
        ordinary = [series[d] for d, k in window if not k]
        past = ordinary if len(ordinary) >= sl.MIN_HISTORY else [series[d] for d, _ in window]
        base = statistics.median(past)
        spread = sl._spread(past, base)
        value = series[day]
        z = (value - base) / spread
        out.append((value, base, spread, z))
        event.append(abs(z) >= sl.Z_LIMIT and max(value, base) >= 1)
    _STATES[key] = out
    return out


def _series_state(series: dict[str, float], ordered: list[str], i: int):
    """(value, baseline, spread, z) of one series on ordered[i] against the days before it (see _states), or None."""
    return _states(series, ordered)[i]


def story_days(days: dict) -> list[str]:
    """The days a story can be written for: at least MIN_HISTORY days of history before them."""
    return sorted(days["all"])[sl.MIN_HISTORY:]


def _direction(value: float, base: float, z: float, floor: float) -> str:
    """'up'/'down' for an event (4 spreads or more from the usual), '*_slight' for 2 to 4 spreads or a move of a quarter or more, 'usual' otherwise."""
    if max(value, base) < floor:
        return "usual"
    if abs(z) >= sl.Z_LIMIT:
        return "up" if z > 0 else "down"
    ratio = value / base if base > 0 else 1.0
    if abs(z) >= SLIGHT_Z or ((ratio >= RATIO_HIGH or ratio <= RATIO_LOW) and abs(value - base) >= MIN_MOVE):
        return "up_slight" if value > base else "down_slight"
    return "usual"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _rank_phrase(by_day: dict, ordered: list[str], i: int, sig: str) -> str | None:
    upto = [by_day[d][sig] for d in ordered[: i + 1] if sig in by_day[d]]
    if len(upto) < 10:
        return None
    rank = 1 + sum(1 for v in upto if v > upto[-1])
    if rank > 3:
        return None
    return f"the largest of the {len(upto)} days held so far" if rank == 1 else f"the {_ordinal(rank)} largest of the {len(upto)} days held so far"


def build_request(days: dict, drift_rows: list[dict], day: str, scope: str, quality: dict | None = None) -> dict:
    by_day = days[scope] if scope == "india" else days["all"]
    ordered = sorted(by_day)
    i = ordered.index(day)
    facts: list[dict] = []
    for n, sig in enumerate(SCOPE_SIGNALS[scope], start=1):
        series = {d: by_day[d][sig] for d in ordered if sig in by_day[d]}
        st = _series_state(series, ordered, i)
        if st is None:
            continue
        value, base, spread, z = st
        direction = _direction(value, base, z, floor_for(scope, sig))
        pct = sig == "india_share"
        disp = _pct if pct else _fmt
        fact = {"id": f"F{n}", "kind": "fact", "column": sig, "label": LABELS[sig], "scope": scope, "day": day, "direction": direction, "value": disp(value), "usual": disp(base), "_z": round(z, 1)}
        if base >= 1 and not pct:
            fact["times_usual"] = f"{value / base:.1f}"
        if direction in ("up", "down"):
            streak = 0
            for j in range(i - 1, -1, -1):
                sj = _series_state(series, ordered, j)
                if sj is None or _direction(sj[0], sj[1], sj[3], floor_for(scope, sig)) != direction:
                    break
                streak += 1
            fact["days_in_a_row"] = str(streak + 1)
            rank = _rank_phrase(by_day, ordered, i, sig)
            if rank and direction == "up":
                fact["rank_phrase"] = rank
        facts.append(fact)
    patterns = _patterns(facts, drift_rows, day, scope)
    derived = _derived(days, quality, ordered, i, day, scope, facts)
    steady = [f for f in facts if f["direction"] == "usual"]
    if steady:
        text = "Every measure was in line with the usual." if len(steady) == len(facts) else "In line with the usual: " + ", ".join(SHORT_LABELS[f["column"]] for f in steady) + "."
        derived.append({"id": f"D{len(derived) + 1}", "kind": "derived", "derived": "steady_summary", "direction": "usual", "cites": [f["id"] for f in steady], "statement": text})
    event_facts = sorted((f for f in facts if f["direction"] in ("up", "down")), key=lambda f: -abs(f["_z"]))
    conclusions = [d["id"] for d in derived if d.get("conclusion") and d["direction"] in ("up", "down")]      # a conclusion is an event only when the thing it describes moved clearly
    events = [p["id"] for p in patterns] + conclusions + [f["id"] for f in event_facts]
    for f in facts:
        f.pop("_z")
    return {"day": day, "scope": scope, "facts": facts, "patterns": patterns, "derived": derived, "caveats": dict(CAVEATS), "footer": FOOTER, "events": events,
            "date_words": f"{date.fromisoformat(day).day} {date.fromisoformat(day).strftime('%B')}"}


def _derived(days: dict, quality: dict | None, ordered: list[str], i: int, day: str, scope: str, facts: list[dict]) -> list[dict]:
    out: list[dict] = []
    by_col = {f["column"]: f for f in facts}
    who = "India's changed products" if scope == "india" else "the changed products"
    cur = days[scope][day]
    new, anyp = cur["new_products"], cur["any_products"]
    if anyp >= MIN_COUNT_FOR_SHARES and "any_products" in by_col:
        # 1. changed products = new + existing (an identity on distinct products)
        existing = {d: days[scope][d]["any_products"] - days[scope][d]["new_products"] for d in ordered if d in days[scope]}
        st = _series_state(existing, ordered, i)
        item = {"id": f"D{len(out) + 1}", "kind": "derived", "derived": "new_and_existing", "scope": scope, "cites": [by_col[c]["id"] for c in ("any_products", "new_products") if c in by_col],
                "identity": f"{_fmt(anyp)} = {_fmt(new)} + {_fmt(anyp - new)}", "direction": "usual",
                "any_n": _fmt(anyp), "new_n": _fmt(new), "existing_n": _fmt(anyp - new), "existing_share": round((anyp - new) / anyp, 3), "existing_pct": _pct_short((anyp - new) / anyp),
                "statement": f"Of {_fmt(anyp)} changed products, {_fmt(new)} were new and {_fmt(anyp - new)} were existing products that were edited."}
        if st:
            item["direction"] = _direction(st[0], st[1], st[3], 20)
            item["usual_existing"] = _fmt(st[1])
        out.append(item)
        # 2. shares of the changed products
        for sig, phrase in SHARE_PARTS.items():
            share = {d: days[scope][d][sig] / days[scope][d]["any_products"] for d in ordered if d in days[scope] and days[scope][d]["any_products"] >= MIN_COUNT_FOR_SHARES}
            st = _series_state(share, ordered, i)
            if not st:
                continue
            direction = _direction(st[0], st[1], st[3], 0.0)
            if direction == "usual":
                continue
            out.append({"id": f"D{len(out) + 1}", "kind": "derived", "derived": "share_of_changed", "scope": scope, "cites": [by_col[sig]["id"], by_col["any_products"]["id"]],
                        "direction": direction, "value": _pct(st[0]), "usual": _pct(st[1]), "value_whole": _pct_short(st[0]), "usual_whole": _pct_short(st[1]), "share": round(st[0], 4), "sig": sig,
                        "statement": f"{_pct(st[0])} of {who} {phrase}, against a usual {_pct(st[1])}."})
    # 2b. India's part of each change type, against its part of all changed products
    if scope == "all" and "india" in days and day in days["india"] and "any_products" in by_col and anyp > 0:
        base_share = days["india"][day]["any_products"] / anyp
        parts = []
        for sig, label in (("nutrition_products", "nutrition changes"), ("ingredients_products", "ingredients changes")):
            all_c, ind_c = days["all"][day][sig], days["india"][day].get(sig, 0.0)
            if all_c < 50 or base_share <= 0 or sig not in by_col:
                continue
            ratio = (ind_c / all_c) / base_share
            if (ratio >= 1.5 and ind_c >= 10 and ind_c / all_c >= 0.10) or (ratio <= 2 / 3 and all_c >= 100 and base_share >= 0.10):
                parts.append({"label": label, "sig": sig, "relation": "over" if ratio >= 1.5 else "under", "india": _fmt(ind_c), "all": _fmt(all_c), "pct": _pct_short(ind_c / all_c)})
        if parts:
            out.append({"id": f"D{len(out) + 1}", "kind": "derived", "derived": "part_of_whole", "scope": scope, "direction": "usual", "parts": parts, "base_pct": _pct_short(base_share),
                        "cites": [by_col["any_products"]["id"]] + [by_col[p["sig"]]["id"] for p in parts],
                        "statement": "India made up " + " and ".join(f"{p['pct']} of the {p['label']}" for p in parts) + f", although it had {_pct_short(base_share)} of all changed products."})
    # 2c. outside India, does the same change type also stand out?
    if scope == "all" and "india" in days and day in days["india"]:
        entries = []
        for sig, label in (("nutrition_products", "nutrition changes"), ("ingredients_products", "ingredients changes")):
            if sig not in by_col or by_col[sig]["direction"] not in ("up", "up_slight"):
                continue
            ind_s = {d: days["india"][d][sig] for d in ordered if d in days["india"] and sig in days["india"][d]}
            rest_s = {d: days["all"][d][sig] - ind_s.get(d, 0.0) for d in ordered}
            st_i, st_r = _series_state(ind_s, ordered, i), _series_state(rest_s, ordered, i)
            if not st_i or not st_r:
                continue
            idir, rdir = _direction(st_i[0], st_i[1], st_i[3], 10), _direction(st_r[0], st_r[1], st_r[3], 10)
            if idir in ("up", "up_slight"):
                entries.append({"label": label, "sig": sig, "kind": "part_not_all" if rdir in ("up", "up_slight") else "all_in_india", "rest_value": _fmt(st_r[0]), "rest_usual": _fmt(st_r[1]),
                                "india_value": _fmt(st_i[0]), "india_usual": _fmt(st_i[1])})
        if entries:
            out.append({"id": f"D{len(out) + 1}", "kind": "derived", "derived": "rest_contrast", "scope": scope, "direction": "usual", "entries": entries, "cites": [by_col[e["sig"]]["id"] for e in entries],
                        "statement": " ".join(f"Outside India, {e['label']} were {'also higher than' if e['kind'] == 'part_not_all' else 'about'} usual ({e['rest_value']}, against {e['rest_usual']})." for e in entries)})
    # 3. all = India + the rest of the world
    if scope == "all" and "india" in days and day in days["india"] and "any_products" in by_col:
        india_series = {d: days["india"][d]["any_products"] for d in ordered if d in days["india"]}
        rest_series = {d: days["all"][d]["any_products"] - india_series.get(d, 0.0) for d in ordered}
        st_rest = _series_state(rest_series, ordered, i)
        st_ind = _series_state(india_series, ordered, i)
        if st_rest and st_ind:
            rest_dir = _direction(st_rest[0], st_rest[1], st_rest[3], 100)
            india_dir = _direction(st_ind[0], st_ind[1], st_ind[3], 20)
            item = {"id": f"D{len(out) + 1}", "kind": "derived", "derived": "india_and_rest", "scope": scope,
                    "cites": [by_col["any_products"]["id"]] + ([by_col["india_share"]["id"]] if "india_share" in by_col else []),
                    "identity": f"{_fmt(anyp)} = {_fmt(india_series[day])} + {_fmt(rest_series[day])}", "direction": "usual",
                    "india_value": _fmt(india_series[day]), "india_usual": _fmt(st_ind[1]), "rest_value": _fmt(rest_series[day]), "rest_usual": _fmt(st_rest[1]), "rest_direction": rest_dir, "india_direction": india_dir,
                    "statement": f"Outside India, {_fmt(rest_series[day])} products changed, against a usual {_fmt(st_rest[1])}; India had {_fmt(india_series[day])}, against a usual {_fmt(st_ind[1])}."}
            all_dir = by_col["any_products"]["direction"]
            if all_dir in ("up", "up_slight") and india_dir == "up" and rest_dir in ("usual", "up_slight", "down_slight"):
                item["direction"] = "up"
                item["conclusion"] = "concentrated_in_india"
                item["conclusion_wording"] = "the increase is concentrated in India"
            elif all_dir in ("up", "up_slight") and rest_dir in ("up", "up_slight") and india_dir in ("usual", "down_slight", "up_slight"):
                item["direction"] = "up"
                item["conclusion"] = "outside_india"
                item["conclusion_wording"] = "the increase is outside India"
            elif all_dir == "usual" and india_dir == "up" and rest_dir in ("down", "down_slight"):
                item["direction"] = "up"
                item["conclusion"] = "offset_by_rest"
                item["conclusion_wording"] = "India's higher count is offset by a lower count elsewhere"
            elif "up" in (rest_dir, india_dir) or "up_slight" in (rest_dir, india_dir):
                item["direction"] = "up"
            elif "down" in (rest_dir, india_dir) or "down_slight" in (rest_dir, india_dir):
                item["direction"] = "down"
            out.append(item)
    # 4. the open-flag bridge
    if quality and scope in quality:
        q = quality[scope]
        qd = sorted(q)
        if day in q and qd.index(day) > 0:
            prev = qd[qd.index(day) - 1]
            delta = q[day]["open_spans"] - q[prev]["open_spans"]
            carried, opened, vanished = q[day]["carried_in"], q[day]["opened_on_known"], q[day]["vanished"]
            if abs(delta - (carried + opened - vanished)) < 0.5 and delta != 0:
                deltas = {d: q[d]["open_spans"] - q[qd[k - 1]]["open_spans"] for k, d in enumerate(qd) if k > 0}
                order_d = sorted(deltas)
                st = _series_state(deltas, order_d, order_d.index(day))
                word = "rose" if delta > 0 else "fell"
                where = "In India, open" if scope == "india" else "Open"
                item = {"id": f"D{len(out) + 1}", "kind": "derived", "derived": "flag_bridge", "scope": scope, "cites": [],
                        "identity": f"{_fmt(delta)} = {_fmt(carried)} + {_fmt(opened)} - {_fmt(vanished)}", "direction": "usual", "sign": "up" if delta > 0 else "down",
                        "delta_abs": _fmt(abs(delta)), "carried": _fmt(carried), "opened_known": _fmt(opened), "ended": _fmt(vanished), "new_flags": _fmt(carried + opened), "opened_share_of_new": round(opened / max(carried + opened, 1), 3),
                        "statement": f"{where} flags {word} by {_fmt(abs(delta))}: {_fmt(carried)} on newly seen products that arrived already flagged, {_fmt(opened)} opened on products already known, and {_fmt(vanished)} ended."}
                if st:
                    item["usual_change"] = _fmt(st[1])
                    item["direction"] = _direction(st[0], st[1], st[3], 1000)
                if delta > 0 and carried / max(carried + opened, 1) >= CARRIED_SHARE_FOR_CONCLUSION:
                    item["carried_share"] = _pct(carried / (carried + opened))
                    item["conclusion"] = "rise_from_newly_seen_products"
                    item["conclusion_wording"] = "almost all of that comes from products seen for the first time that arrived already flagged"
                out.append(item)
    return out


def _patterns(facts: list[dict], drift_rows: list[dict], day: str, scope: str) -> list[dict]:
    out: list[dict] = []
    by_col = {f["column"]: f for f in facts}
    if scope == "india" and by_col.get("any_products", {}).get("direction") == "up":
        out.append({"id": "P1", "kind": "pattern", "direction": "up", "pattern": "regional_burst", "cites": [by_col["any_products"]["id"]],
                    "rule": "India's count of changed products is far above its usual level",
                    "wording": "consistent with a burst of edits concentrated in India",
                    "statement": f"India had {by_col['any_products']['value']} products with at least one change, {by_col['any_products'].get('times_usual', '')} times the usual {by_col['any_products']['usual']}, consistent with a burst of edits concentrated in India."})
    if scope == "all":
        todays = [r for r in drift_rows if r["day"] == day]
        cov = [r for r in todays if r["check"] == "coverage_rise"]
        if len(cov) >= MIN_COVERAGE_WARNINGS:
            out.append({"id": "P2", "kind": "pattern", "direction": "up", "pattern": "wide_coverage_jump", "fields_with_a_jump": str(len(cov)), "must_state": [str(len(cov))],
                        "rule": f"{MIN_COVERAGE_WARNINGS} or more fields were filled far more often than usual in one day's file",
                        "wording": "consistent with a batch of products added with unusually complete entries",
                        "statement": f"{len(cov)} fields were filled more often than usual in that day's file, consistent with a batch of products added with unusually complete entries."})
        for r in todays:
            if r["check"] == "failure_rate":
                col = r["detail"].split(":", 1)[1].split(" ", 1)[0].rstrip(":") if r["detail"].startswith("tags:") else "a tag column"
                nums = r["detail"].split("(")[1].split(")")[0].split(" per 100")[0]
                lo_hi = r["detail"].split("had ")[-1]
                out.append({"id": f"P3{'' if not any(p['id'] == 'P3' for p in out) else 'b'}", "kind": "pattern", "direction": "up", "pattern": "tag_failure_spike", "column": col, "label": col.replace("_", " "),
                            "dropped_per_100": nums, "usual_range_per_100": lo_hi, "must_state": [nums] + lo_hi.split("-"),
                            "rule": "the drift monitor raised a failure-rate alert on one tag column in one day's file",
                            "wording": "consistent with a formatting problem in that day's file",
                            "statement": f"The {col.replace('_', ' ')} were dropped for {nums} of every 100 products, against a usual {lo_hi}, consistent with a formatting problem in that day's file."})
    return out


SKIP_KEYS = {"id", "kind", "label", "column", "scope", "day", "direction", "sign", "rule", "wording", "pattern", "cites", "derived", "conclusion", "conclusion_wording"}


def all_items(request: dict) -> dict[str, dict]:
    return {x["id"]: x for x in request["facts"] + request["patterns"] + request["derived"]}


def known_numbers(request: dict, cited: list[str]) -> set[float]:
    """Every number a sentence citing these ids may state: the display forms of the cited facts, derived facts and patterns (their statements too), and the date parts."""
    import re
    nums: set[float] = set()
    d = date.fromisoformat(request["day"])
    nums.update({float(d.day), float(d.month), float(d.year)})
    items = all_items(request)
    for cid in cited:
        item = items.get(cid)
        if not item:
            continue
        for k, v in item.items():
            if k in SKIP_KEYS:
                continue
            for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", str(v)):
                nums.add(float(tok.replace(",", "")))
        if "dropped_per_100" in item:
            nums.add(100.0)
        for cc in item.get("cites", []):
            nums |= known_numbers(request, [cc])
    return nums
