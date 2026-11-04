"""Plain-words evidence for a broken arithmetic rule, with the numbers computed BY CODE from the rules engine (item 23).

The same figures the Label Studio cards print for a human: what a printed value converts to, what the other nutrients add up to. They are shown in the public line of a status and, in
a retry, given back to the model about ITS OWN reading (never about the stored record: the reader must stay independent of the record). A model is never asked to compute them.
Values are per 100 g or ml, with this project's field names (energy_kcal, energy_kj, fat, saturated_fat, carbohydrates, sugars, fiber, proteins, salt, sodium).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_triage_ml"))
import rules_lib as rl  # noqa: E402

from fix_candidates import rule_input  # noqa: E402


def _g(x: float) -> str:
    return f"{x:.3g}" if abs(x) < 1000 else f"{x:,.0f}"


def explain(values: dict, rule: str) -> str:
    """One sentence saying what the rule compares and the computed figures. Falls back to the rule name for a rule not listed."""
    v, n = values, rule_input(values)
    try:
        if rule in ("energy-value-in-kcal-greater-than-in-kj", "energy-value-in-kcal-and-kj-are-reversed", "energy-value-in-kcal-does-not-match-value-in-kj"):
            return f"{_g(v['energy_kcal'])} kcal is about {_g(v['energy_kcal'] * 4.184)} kJ (1 kcal is 4.184 kJ), but the value is {_g(v['energy_kj'])} kJ"
        if rule.startswith("energy-value-in-kj-does-not-match-value-computed"):
            return f"the nutrients add up to about {_g(rl.computed_energy(n, 'kj'))} kJ, but the value is {_g(v['energy_kj'])} kJ"
        if rule.startswith("energy-value-in-kcal-does-not-match-value-computed"):
            return f"the nutrients add up to about {_g(rl.computed_energy(n, 'kcal'))} kcal, but the value is {_g(v['energy_kcal'])} kcal"
        if rule == "value-over-3911-energy":
            return f"{_g(v['energy_kj'])} kJ in 100 g is more than the highest possible energy (3,911 kJ)"
        if rule == "salt-does-not-match-sodium":
            return f"{_g(v['sodium'])} g of sodium is about {_g(v['sodium'] * rl.SALT_PER_SODIUM)} g of salt, but the value for salt is {_g(v['salt'])} g"
        if rule == "sugars-plus-starch-greater-than-carbohydrates":
            return f"sugars ({_g(v['sugars'])} g) are more than the carbohydrates ({_g(v['carbohydrates'])} g) they are part of"
        if rule == "saturated-fat-greater-than-fat":
            return f"saturated fat ({_g(v['saturated_fat'])} g) is more than the total fat ({_g(v['fat'])} g)"
        if rule == "value-over-105":
            worst = max(((k, x) for k, x in v.items() if not k.startswith("energy") and x is not None), key=lambda kv: kv[1])
            return f"{worst[0].replace('_', ' ')} is {_g(worst[1])} g in 100 g, which is not possible"
        if rule == "value-total-over-105":
            tot = sum(v.get(k) or 0 for k in ("fat", "carbohydrates", "proteins", "salt"))
            return f"fat, carbohydrates, protein and salt add up to {_g(tot)} g in 100 g, which is not possible"
    except (KeyError, TypeError):
        pass
    return rule.replace("-", " ")
