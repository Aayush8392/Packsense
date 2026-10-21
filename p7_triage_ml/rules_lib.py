"""Rule verdicts: the nutrition flags that arithmetic or physics can decide, decided by code with OFF's own tolerances (context file, decision 23).

Source of every number: OFF's open-source `lib/ProductOpener/DataQualityFood.pm` (checks) and `Nutrition.pm` (energy computed from nutrients), read 2026-10-21.
Pure Python, no Spark, no network: a product's nutrient values go in, one verdict per rule comes out.

Inputs are per 100 g or 100 ml, in grams, except `energy-kj` (kJ) and `energy-kcal` (kcal). A missing nutrient is a missing key. Two things OFF reads that
this table does not carry are not applied: the `<`, `~`, `<=` modifiers on a value (OFF counts a quoted part as 0 and skips a quoted total) and the
per-category switch that turns the energy-from-nutrients error off. Both can only make OFF fire LESS than these rules do, so a verdict here is a superset.
"""
from __future__ import annotations

from dataclasses import dataclass

RULES_VERSION = 1

# --- tolerances (OFF DataQualityFood.pm) ----------------------------------------------------------------------------------------------------------
KJ_PER_KCAL_LOW, KJ_PER_KCAL_HIGH, KJ_KCAL_SLACK = 3.7, 4.7, 2
ENERGY_ERROR_RATIO, ENERGY_WARNING_RATIO, ENERGY_SLACK = 0.30, 0.15, 5
ENERGY_MIN_KJ, ENERGY_MIN_KCAL = 55, 13                  # the computed-energy check only runs above these
SALT_PER_SODIUM, SALT_SODIUM_TOLERANCE = 2.5, 0.1
PART_TOLERANCE_SMALL, PART_TOLERANCE_LARGE, PART_LARGE_FROM = 0.01, 0.1, 10
NUTRIENT_MAX_G, TOTAL_MAX_G, ENERGY_MAX_KJ = 105, 105, 3911
TRACE_G = {"carbohydrates": 0.5, "sugars": 0.5, "proteins": 0.5, "fat": 0.5, "saturated-fat": 0.1, "salt": 0.0125}   # a stated 0 total counts as this

# energy from nutrients: key -> (kJ per g, kcal per g), OFF Nutrition.pm `%energy_from_nutrients{europe}`
FACTORS = {"carbohydrates_minus_polyols": (17, 4), "polyols_minus_erythritol": (10, 2.4), "proteins": (17, 4), "fat": (37, 9),
           "salatrim": (25, 6), "alcohol": (29, 7), "organic_acids": (13, 3), "fiber": (8, 2), "erythritol": (0, 0)}
POLYOL_PARTS = ("erythritol", "isomalt", "maltitol", "sorbitol")


@dataclass(frozen=True)
class Verdict:
    status: str                      # "violated", "ok" or "not_applicable" (an input is missing, or the rule does not apply)
    severity: str | None = None      # "error" or "warning" when violated
    deviation: float | None = None   # how far past the limit, in the rule's own unit; None when not violated or not meaningful


OK = Verdict("ok")
NA = Verdict("not_applicable")


def violated(deviation: float | None = None, severity: str = "error") -> Verdict:
    return Verdict("violated", severity, None if deviation is None else round(deviation, 4))


# --- energy ---------------------------------------------------------------------------------------------------------------------------------------

def kcal_greater_than_kj(n: dict) -> Verdict:
    kj, kcal = n.get("energy-kj"), n.get("energy-kcal")
    if kj is None or kcal is None:
        return NA
    return violated(kcal - kj) if kcal > kj else OK


def kcal_and_kj_reversed(n: dict) -> Verdict:
    kj, kcal = n.get("energy-kj"), n.get("energy-kcal")
    if kj is None or kcal is None:
        return NA
    return violated() if kcal > kj and kcal > KJ_PER_KCAL_LOW * kj - KJ_KCAL_SLACK and kcal < KJ_PER_KCAL_HIGH * kj + KJ_KCAL_SLACK else OK


def kcal_does_not_match_kj(n: dict) -> Verdict:
    kj, kcal = n.get("energy-kj"), n.get("energy-kcal")
    if kj is None or kcal is None:
        return NA
    low, high = KJ_PER_KCAL_LOW * kcal - KJ_KCAL_SLACK, KJ_PER_KCAL_HIGH * kcal + KJ_KCAL_SLACK
    if kj < low:
        return violated(low - kj)
    if kj > high:
        return violated(kj - high)
    return OK


def computed_energy(n: dict, unit: str) -> float | None:
    """Energy OFF computes from the other nutrients; None when carbohydrates, fat or proteins is missing (OFF then computes nothing)."""
    if any(n.get(k) is None for k in ("carbohydrates", "fat", "proteins")):
        return None
    i = 0 if unit == "kj" else 1
    polyols = n.get("polyols")
    if polyols is None:
        parts = [n[k] for k in POLYOL_PARTS if n.get(k) is not None]
        polyols = sum(parts) if parts else 0
    g = lambda k: n.get(k) or 0                                                       # noqa: E731
    grams = {"carbohydrates_minus_polyols": g("carbohydrates") - polyols, "polyols_minus_erythritol": polyols - g("erythritol"), "proteins": g("proteins"),
             "fat": g("fat"), "salatrim": g("salatrim"), "alcohol": g("alcohol"), "organic_acids": g("organic_acids"), "fiber": g("fiber"),
             "erythritol": g("erythritol")}
    return sum(grams[k] * FACTORS[k][i] for k in FACTORS)


def _energy_vs_computed(n: dict, unit: str) -> Verdict:
    specified, computed = n.get(f"energy-{unit}"), computed_energy(n, unit)
    if specified is None or computed is None:
        return NA
    floor = ENERGY_MIN_KJ if unit == "kj" else ENERGY_MIN_KCAL
    if specified <= floor and computed <= floor:
        return NA
    for ratio, severity in ((ENERGY_ERROR_RATIO, "error"), (ENERGY_WARNING_RATIO, "warning")):
        low, high = specified * (1 - ratio) - ENERGY_SLACK, specified * (1 + ratio) + ENERGY_SLACK
        if computed < low or computed > high:
            return violated(low - computed if computed < low else computed - high, severity)
    return OK


def energy_kj_does_not_match_computed(n: dict) -> Verdict:
    return _energy_vs_computed(n, "kj")


def energy_kcal_does_not_match_computed(n: dict) -> Verdict:
    return _energy_vs_computed(n, "kcal")


def energy_over_3911(n: dict) -> Verdict:
    kj = n.get("energy-kj")
    if kj is None:
        return NA
    return violated(kj - ENERGY_MAX_KJ) if kj > ENERGY_MAX_KJ else OK


# --- salt, sodium and the parts of a total --------------------------------------------------------------------------------------------------------

def salt_does_not_match_sodium(n: dict) -> Verdict:
    salt, sodium = n.get("salt"), n.get("sodium")
    if salt is None or sodium is None:
        return NA
    gap = round(abs(sodium * SALT_PER_SODIUM - salt), 6)                            # rounded so float noise cannot tip a gap of exactly 0.1
    return violated(gap - SALT_SODIUM_TOLERANCE) if gap > SALT_SODIUM_TOLERANCE else OK


def _total_less_than_parts(n: dict, total_key: str, part_keys: tuple[str, ...]) -> Verdict:
    total = n.get(total_key)
    parts = [n[k] for k in part_keys if n.get(k) is not None]
    if total is None or not parts:
        return NA
    if total == 0:
        total = TRACE_G.get(total_key, 0)
    tolerance = PART_TOLERANCE_LARGE if total >= PART_LARGE_FROM else PART_TOLERANCE_SMALL
    excess = round(round(sum(parts), 2) - round(total, 2), 6)
    return violated(excess - tolerance) if excess > tolerance else OK


def sugars_plus_starch_greater_than_carbohydrates(n: dict) -> Verdict:
    return _total_less_than_parts(n, "carbohydrates", ("sugars", "starch"))


def saturated_fat_greater_than_fat(n: dict) -> Verdict:
    return _total_less_than_parts(n, "fat", ("saturated-fat",))


# --- impossible quantities ------------------------------------------------------------------------------------------------------------------------

def value_over_105(n: dict) -> Verdict:
    """Any nutrient in grams over 105 per 100 g. Energy is not a mass, so it is left out."""
    worst = max((v for k, v in n.items() if not k.startswith("energy") and v is not None), default=None)
    if worst is None:
        return NA
    return violated(worst - NUTRIENT_MAX_G) if worst > NUTRIENT_MAX_G else OK


def value_total_over_105(n: dict) -> Verdict:
    keys = ("fat", "carbohydrates", "proteins", "salt")
    if all(n.get(k) is None for k in keys):
        return NA
    total = sum(n.get(k) or 0 for k in keys)
    return violated(total - TOTAL_MAX_G) if total > TOTAL_MAX_G else OK


RULES = {
    "energy-value-in-kcal-greater-than-in-kj": kcal_greater_than_kj,
    "energy-value-in-kcal-and-kj-are-reversed": kcal_and_kj_reversed,
    "energy-value-in-kcal-does-not-match-value-in-kj": kcal_does_not_match_kj,
    "energy-value-in-kj-does-not-match-value-computed-from-other-nutrients": energy_kj_does_not_match_computed,
    "energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients": energy_kcal_does_not_match_computed,
    "value-over-3911-energy": energy_over_3911,
    "salt-does-not-match-sodium": salt_does_not_match_sodium,
    "sugars-plus-starch-greater-than-carbohydrates": sugars_plus_starch_greater_than_carbohydrates,
    "saturated-fat-greater-than-fat": saturated_fat_greater_than_fat,
    "value-over-105": value_over_105,
    "value-total-over-105": value_total_over_105,
}


def verdicts(nutrients: dict) -> dict[str, Verdict]:
    """Every rule's verdict for one product's per-100 nutrient values."""
    return {name: rule(nutrients) for name, rule in RULES.items()}


def rule_for_family(family: str) -> str | None:
    """The rule that decides a flag family (the flag name with its `nutrition-<source>-<prepared>-<basis>-` prefix stripped), or None when no rule does.
    The family of the 'does not match computed' flags carries kj or kcal in its name; `value-over-105-<nutrient>` is one family per nutrient."""
    family = family.replace("-may-not-match-value-computed-", "-does-not-match-value-computed-")     # the warning twin of the error flag
    if family in RULES:
        return family
    if family.startswith("value-over-105-"):
        return "value-over-105"
    return None
