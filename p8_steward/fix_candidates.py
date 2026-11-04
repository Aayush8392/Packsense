"""Candidate fixes for a nutrition flag, found by code and checked by the project's own rules (roadmap item 23: the steward's checkable part).

The sample of six showed what goes wrong when a model invents a fix: wrong arithmetic, the wrong field, and no sense of the usual slips (milligrams typed as
grams, a per-serving column used as the per-100 column). This module does the checkable part in code: from a product's stored per-100 values it builds the
usual repairs, keeps only those after which NO rule of p7_triage_ml/rules_lib.py is violated, and ranks them by how few fields they change.

What a surviving candidate means, and does not: it clears OFF's arithmetic checks. It is NOT shown to be what the pack says. Two candidates can both clear the
rules (which side of a salt/sodium pair is wrong?); the list then keeps both, and the label decides. No candidate means the stored values do not break a rule
(the flag may come from a basis the table does not carry) or no usual slip repairs them.

Pure Python, no network, no model. Values are per 100 g or 100 ml; energy in kcal and kJ, everything else in grams.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_triage_ml"))
import rules_lib as rl  # noqa: E402

FIELDS = ("energy_kcal", "energy_kj", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt", "sodium")
RULE_KEY = {"energy_kcal": "energy-kcal", "energy_kj": "energy-kj", "fat": "fat", "saturated_fat": "saturated-fat", "carbohydrates": "carbohydrates",
            "sugars": "sugars", "fiber": "fiber", "proteins": "proteins", "salt": "salt", "sodium": "sodium"}
KJ_PER_KCAL = 4.184
# the kinds of repair, in the order used to break ties between candidates that change the same number of fields
RANK = {"revert": 0, "derive": 1, "scale_flagged": 2, "scale_all": 3, "basis_then_derive": 4}


def rule_input(values: dict) -> dict:
    return {RULE_KEY[f]: v for f, v in values.items() if f in RULE_KEY and v is not None}


def violations(values: dict) -> set[str]:
    """The names of the rules the values break (a warning counts)."""
    return {name for name, v in rl.verdicts(rule_input(values)).items() if v.status == "violated"}


def clean(values: dict) -> dict:
    return {f: values.get(f) for f in FIELDS if values.get(f) is not None}


def _round(v: float) -> float:
    return round(v, 4)


def _scaled(values: dict, fields, factor: float) -> dict:
    out = dict(values)
    for f in fields:
        if out.get(f) is not None:
            out[f] = _round(out[f] * factor)
    return out


def _derive_options(values: dict, broken: set[str]) -> list[tuple[str, dict]]:
    """One field recomputed from another, for each side of a broken pair."""
    opts = []
    kcal, kj = values.get("energy_kcal"), values.get("energy_kj")
    if any("kcal-does-not-match-value-in-kj" in r or "reversed" in r or "kcal-greater" in r for r in broken):
        if kj is not None:
            opts.append((f"energy kcal from the kJ figure (kJ / 4.184) = {_round(kj / KJ_PER_KCAL)}", {**values, "energy_kcal": _round(kj / KJ_PER_KCAL)}))
        if kcal is not None:
            opts.append((f"energy kJ from the kcal figure (kcal x 4.184) = {_round(kcal * KJ_PER_KCAL)}", {**values, "energy_kj": _round(kcal * KJ_PER_KCAL)}))
    if any("computed-from-other-nutrients" in r for r in broken):
        n = rule_input(values)
        ck, cj = rl.computed_energy(n, "kcal"), rl.computed_energy(n, "kj")
        if ck is not None:
            opts.append((f"energy kcal from the nutrients (OFF factors) = {_round(ck)}", {**values, "energy_kcal": _round(ck)}))
        if cj is not None:
            opts.append((f"energy kJ from the nutrients (OFF factors) = {_round(cj)}", {**values, "energy_kj": _round(cj)}))
    if any("salt-does-not-match-sodium" in r for r in broken):
        if values.get("sodium") is not None:
            opts.append((f"salt from sodium (x 2.5) = {_round(values['sodium'] * rl.SALT_PER_SODIUM)}", {**values, "salt": _round(values["sodium"] * rl.SALT_PER_SODIUM)}))
        if values.get("salt") is not None:
            opts.append((f"sodium from salt (/ 2.5) = {_round(values['salt'] / rl.SALT_PER_SODIUM)}", {**values, "sodium": _round(values["salt"] / rl.SALT_PER_SODIUM)}))
    return opts


def candidates(current: dict, previous: dict | None = None, serving: float | None = None, max_candidates: int = 6) -> list[dict]:
    """Repairs that leave no rule violated, simplest first. `serving` is the serving size (g or ml) when the record has one.

    Each candidate: {'kind', 'description', 'values' (the full repaired set), 'changes' ({field: (old, new)})}.
    """
    cur = clean(current)
    broken = violations(cur)
    if not broken:
        return []
    raw: list[tuple[str, str, dict]] = []
    if previous:
        prev = clean(previous)
        if prev != cur:
            raw.append(("revert", "go back to the previous revision's values", prev))
    for text, values in _derive_options(cur, broken):
        raw.append(("derive", text, values))
    factors = [(0.001, "divide by 1000 (milligrams typed as grams)"), (1000.0, "multiply by 1000 (grams typed as milligrams)")]
    if serving:
        factors += [(serving / 100.0, f"scale by {serving:g}/100 (per-serving column used as per-100)"),
                    (100.0 / serving, f"scale by 100/{serving:g} (per-100 column used as per-serving)")]
    flagged = [f for f in FIELDS if f not in ("energy_kcal", "energy_kj") and (cur.get(f) or 0) > rl.NUTRIENT_MAX_G]
    pair = [f for f in ("salt", "sodium") if f in cur]
    for factor, label in factors:
        unit_slip = factor in (0.001, 1000.0)             # a milligram/gram slip hits single mass fields, never the whole table or the energy
        if flagged:
            raw.append(("scale_flagged", f"{label}: {', '.join(flagged)}", _scaled(cur, flagged, factor)))
        if not unit_slip:                                  # a wrong basis (per serving used as per 100) moves the whole column, energy included
            raw.append(("scale_all", f"{label}: every value", _scaled(cur, FIELDS, factor)))
        if pair and any("salt-does-not-match-sodium" in r for r in broken):
            for side, other in (("salt", "sodium"), ("sodium", "salt")):
                moved = _scaled(cur, [side], factor)
                moved[other] = _round(moved[side] / rl.SALT_PER_SODIUM) if side == "salt" else _round(moved[side] * rl.SALT_PER_SODIUM)
                raw.append(("basis_then_derive", f"{label}: {side} only, then {other} from it", moved))
    seen, out = set(), []
    for kind, text, values in raw:
        key = tuple(sorted((f, round(v, 3)) for f, v in values.items()))
        if key in seen or key == tuple(sorted((f, round(v, 3)) for f, v in cur.items())):
            continue
        seen.add(key)
        if violations(values):
            continue
        changes = {f: (cur.get(f), values.get(f)) for f in FIELDS if cur.get(f) != values.get(f)}
        out.append({"kind": kind, "description": text, "values": values, "changes": changes})
    out.sort(key=lambda c: (len(c["changes"]), RANK[c["kind"]]))
    return out[:max_candidates]
