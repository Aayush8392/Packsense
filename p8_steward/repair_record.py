"""The repaired record and the statements a line can carry (pre-registered in output/review_set/guard_and_statements_prereg.md, section 1; written 2026-11-13).

  repaired_record(before, table)   the stored record with the confirmed line laid on top, plus the partner values code derives (salt <-> sodium, kJ <-> kcal)
  bound_statements(...)            for a stale STORED value that breaks a hard law of the label against a CONFIRMED value of the line: 'the stored X must be at most / at least Y'

Partner rule: when the line gives one side of a pair and not the other, the other side is derived with the fixed ratio and replaces the stored one if the stored one is more than 10% away from it
(no absolute floor: fix_test_lib.complete_partners keeps a stored sodium of 0.00012 against a derived 0.048 because of its 0.05 g floor). Nothing is ever deleted; a stored value the line does not
speak to stays as it is. Bounds exist only for the hard laws (saturated fat at most fat; sugars at most carbohydrates, via the rule 'sugars-plus-starch-greater-than-carbohydrates'); never from the
energy rule (sugar alcohols, fibre conventions and rounding move that sum).
"""
from __future__ import annotations

PAIRS = (("salt", "sodium", 1 / 2.5), ("sodium", "salt", 2.5), ("energy_kcal", "energy_kj", 4.184), ("energy_kj", "energy_kcal", 1 / 4.184))
REL = 0.10
# rule id -> (the field that must be the smaller, the field that must be the larger)
HARD_LAWS = {"saturated-fat-greater-than-fat": ("saturated_fat", "fat"), "sugars-plus-starch-greater-than-carbohydrates": ("sugars", "carbohydrates")}
LABEL = {"saturated_fat": "saturated fat", "fat": "fat", "sugars": "sugars", "carbohydrates": "carbohydrates"}


def repaired_record(before: dict, table: dict) -> tuple[dict, dict]:
    """(record, derived): the record, and the partner values code derived (field -> value)."""
    rec = {**before, **table}
    derived: dict = {}
    for src, dst, factor in PAIRS:
        if src in table and dst not in table:
            d = round(table[src] * factor, 4)
            old = before.get(dst)
            if old is None or abs(old - d) > REL * abs(d):
                rec[dst] = d
                derived[dst] = d
    return rec, derived


def bound_statements(before: dict, table: dict, violated: set[str]) -> list[dict]:
    """One statement for each violated hard law where exactly one side is a stored value the line did not confirm and the other side is confirmed by the line."""
    out = []
    for rule, (small, large) in HARD_LAWS.items():
        if rule not in violated:
            continue
        if large in table and small not in table and before.get(small) is not None:
            stale, other, kind = small, large, "at most"
        elif small in table and large not in table and before.get(large) is not None:
            stale, other, kind = large, small, "at least"
        else:
            continue
        x, y = before[stale], table[other]
        out.append({"rule": rule, "stale_field": stale, "stored": x, "confirmed_field": other, "confirmed": y, "kind": kind,
                    "text": f"The stored {LABEL[stale]} ({x:g} g) is out of date or wrong: the photo shows {LABEL[other]} {y:g} g, so it must be {kind} {y:g} g."})
    return out
