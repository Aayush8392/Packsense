"""Scoring for the 'history key' test of a repair proposer (the agent, or the code baseline). Pure functions, no network, no model.

The test (plan agreed 2026-11-08): for a product whose nutrition error flags OFF removed after a change of the stored per-100 values, a proposer sees the PRE-fix stored values (and for the
agent the raw scan) and proposes a repair. The key is the POST-fix stored values (OFF's own fix). Every proposal falls in exactly one class:
  agrees            every compared field of the flagged group is within 10% of the key (answer_key_lib.matches_key_for_group)
  valid_alternative it does not agree, but the pre-fix record with the proposal applied violates no rule of rules_lib (it may be right where the key is wrong; the rules are loose, so it may also be wrong)
  breaks_rule       the pre-fix record with the proposal applied still violates a rule
  abstain           no proposal
The PRIMARY comparison is paired against the code baseline on the same products: a win is 'agent agrees and code does not', a loss is the reverse, ties are ignored; an alternative counts as
'does not agree' for BOTH. The three-way split and the bracket of precision (agrees only .. agrees plus alternatives) are separate figures with no pass mark. An alternative is also looked at
automatically: which side's values are printed in the scan (agent only / both / key only / neither).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_key_lib as akl  # noqa: E402
import fix_candidates as fc  # noqa: E402
import history_key_scan_check as hk  # noqa: E402
import review_set_lib as rsl  # noqa: E402


def removed_flags(row: dict) -> list[str]:
    return [f for f in (row.get("flags") or "").split("|") if f]


def group_of_row(row: dict) -> str:
    """The highest-priority group among the removed flags (the order of review_set_lib.GROUPS)."""
    groups = [g for g in (rsl.group_of(f) for f in removed_flags(row)) if g]
    return min(groups, key=rsl.ALL_GROUPS.index) if groups else rsl.OTHER


def only_serving_flags(row: dict) -> bool:
    """True when every removed flag concerns the per-serving column: the fix then targeted values we do not score."""
    flags = removed_flags(row)
    return bool(flags) and all("-serving-" in f and "-100g-" not in f for f in flags)


def eligible(row: dict) -> bool:
    return not only_serving_flags(row)


def clean_key(row: dict) -> bool:
    """The clean-key condition (agreed 2026-11-08, from development data only): OFF removed the flags AND the post-fix record passes the whole rule set (errors and warnings of rules_lib).
    The rule set is a superset of OFF's own checks, so a few fixes are dropped that OFF itself would accept; that costs coverage, never the other way."""
    return not fc.violations(key(row))


def before(row: dict) -> dict:
    return hk.side(row, "a")


def key(row: dict) -> dict:
    return hk.side(row, "b")


def serving_of(row: dict) -> float | None:
    parsed = akl.parse_serving(row.get("serving_size") or "") or akl.parse_bracket_serving(row.get("serving_size") or "")
    return parsed[0] if parsed else None


def code_proposal(row: dict) -> dict | None:
    """The code baseline: the simplest repair of fix_candidates that leaves no rule violated (None when it has none)."""
    found = fc.candidates(before(row), serving=serving_of(row), max_candidates=1)
    return found[0]["values"] if found else None


def classify(row: dict, proposal: dict | None) -> str:
    if not proposal:
        return "abstain"
    group = group_of_row(row)
    merged = {**before(row), **{f: v for f, v in proposal.items() if v is not None}}      # the repaired record: judged on every field of the group it carries, not only the ones it changed
    if akl.matches_key_for_group(merged, key(row), group)["match"]:
        return "agrees"
    return "breaks_rule" if fc.violations(merged) else "valid_alternative"


ACTS = ("change to reading", "fill in")


def agent_proposal(decision: dict) -> dict | None:
    """The values the reader proposes (reader_decision.decide output), or None when its action is not a proposal (no change, an abstention)."""
    return dict(decision["per100"]) if decision.get("action") in ACTS and decision.get("per100") else None


PARTNERS = (("sodium", "salt", 2.5), ("salt", "sodium", 1 / 2.5), ("energy_kcal", "energy_kj", 4.184), ("energy_kj", "energy_kcal", 1 / 4.184))      # (printed side, derived side, factor)


def complete_partners(before: dict, reading: dict, proposal: dict) -> dict:
    """PARTNER FILL (method v4, 2026-11-08). When the pack prints one side of a pair (salt/sodium, kJ/kcal), the other side is NOT printed, the stored record holds a value for it and that
    value disagrees with the printed side (the 10% rule), code derives the other side with the fixed ratio and adds it to the proposal. The model still only reads; nothing is added when the
    other side is printed, absent from the record, already in the proposal or already consistent."""
    out = dict(proposal)
    for src, dst, factor in PARTNERS:
        if src in reading and dst not in reading and dst in before and dst not in out:
            derived = round(reading[src] * factor, 4)
            if not akl.field_matches(dst, before[dst], derived):
                out[dst] = derived
    return out


def hybrid_pick(row: dict, reading: dict | None) -> dict | None:
    """HYBRID A (2026-11-08, fixed before it was run): code builds its rule-clearing candidates (fix_candidates, up to six); the model's READING picks the one that agrees with what the pack
    prints on the most fields of the flagged group (ties: the code's own order, fewest changes first). With no reading, or no candidate agreeing on any field, the code's first candidate."""
    cands = fc.candidates(before(row), serving=serving_of(row), max_candidates=6)
    if not cands:
        return None
    fields = akl.GROUP_FIELDS[group_of_row(row)]
    best, best_score = cands[0], (0, 0)
    for rank, c in enumerate(cands):
        both = [f for f in fields if f in (reading or {}) and c["values"].get(f) is not None]
        hits = sum(akl.field_matches(f, c["values"][f], reading[f]) for f in both)
        score = (hits, -(len(both) - hits))
        if hits and score > best_score:
            best, best_score = c, score
    return best["values"]


def hybrid_agent_first(row: dict, filled: dict | None) -> dict | None:
    """HYBRID B: the agent's proposal (with the partner fill) when the repaired record then violates no rule; otherwise the code's first candidate."""
    if filled and not fc.violations({**before(row), **filled}):
        return filled
    return code_proposal(row)


def hybrid_agent_then_reading(row: dict, filled: dict | None, reading: dict | None) -> dict | None:
    """HYBRID C (2026-11-08, designed on development round 1): the agent's proposal when it leaves no rule broken; otherwise the code candidate the model's reading picks (hybrid_pick);
    with no reading the code's first candidate."""
    if filled and not fc.violations({**before(row), **filled}):
        return filled
    return hybrid_pick(row, reading)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def split(classes: list[str]) -> dict:
    n = len(classes)
    count = {k: classes.count(k) for k in ("agrees", "valid_alternative", "breaks_rule", "abstain")}
    proposals = n - count["abstain"]
    return {**count, "products": n, "proposals": proposals, "coverage": proposals / n if n else 0.0,
            "precision_agrees_only": (count["agrees"] / proposals if proposals else None, wilson(count["agrees"], proposals)),
            "precision_agrees_plus_alternatives": ((count["agrees"] + count["valid_alternative"]) / proposals if proposals else None,
                                                   wilson(count["agrees"] + count["valid_alternative"], proposals))}


def paired(agent: list[str], code: list[str]) -> dict:
    """Wins (agent agrees, code does not), losses (reverse), ties ignored; difference in agreement rate with a 95% interval and an exact two-sided sign test."""
    n = len(agent)
    wins = sum(a == "agrees" and c != "agrees" for a, c in zip(agent, code))
    losses = sum(a != "agrees" and c == "agrees" for a, c in zip(agent, code))
    d = (wins - losses) / n if n else 0.0
    se = math.sqrt(max((wins + losses) - (wins - losses) ** 2 / n, 0.0)) / n if n else 0.0
    m = wins + losses
    p = min(1.0, 2 * sum(math.comb(m, i) for i in range(0, min(wins, losses) + 1)) / 2 ** m) if m else 1.0
    return {"products": n, "wins": wins, "losses": losses, "difference": d, "ci95": (d - 1.96 * se, d + 1.96 * se), "sign_test_p": p}


def printed_side(row: dict, proposal: dict, scan_text: str) -> str:
    """For an alternative: which side's values (over the fields they differ on) are printed in the scan text."""
    fields = [f for f in proposal if proposal[f] is not None and f in key(row)
              and not akl.field_matches(f, proposal[f], key(row)[f])]
    if not fields:
        return "no_difference"
    agent_ok = len(akl.grounded_values({f: proposal[f] for f in fields}, scan_text)[1]) == 0
    key_ok = len(akl.grounded_values({f: key(row)[f] for f in fields}, scan_text)[1]) == 0
    return {(True, False): "agent_only", (True, True): "both", (False, True): "key_only", (False, False): "neither"}[(agent_ok, key_ok)]
