"""Does OFF's own fix history agree with the owner's typed answer key? (read-only check, no model, no network)

The idea (owner, 2026-11-08): a contributor's correction is a usable answer key when OFF itself then REMOVED the nutrition error flag, because OFF's rules accept
the new values. This script tests that idea on the products the owner keyed by hand: for each keyed product it finds the first version-to-version step where
the nutrition error flags went from some to none while the stored per-100 values changed, then compares the NEW stored values with the owner's key
(the 10% rule of answer_key_lib, on the fields of the card's flag group).

What it shows and does not: agreement means 'OFF's fix and the owner's reading of the pack are the same'. It says nothing about products nobody fixed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_key_lib as akl  # noqa: E402

FIELDS = ("energy_kcal", "energy_kj", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt", "sodium")
REVIEW = Path(__file__).resolve().parents[1] / "output" / "review_set"
KEY_FILES = ("answer_key_dev_key.json", "answer_key_dev2_key.json", "answer_key_test_key.json", "answer_key_test2_key.json")


def nutrition_errors(version: dict) -> set[str]:
    return {t for t in (version.get("data_quality_errors_tags") or []) if "nutrition" in t}


def values(version: dict) -> dict:
    return {f: version.get(f) for f in FIELDS if version.get(f) is not None}


def changed(before: dict, after: dict) -> bool:
    """True when any stored value differs by more than float noise (the stored numbers carry 1e-12 noise between versions)."""
    for f in set(before) | set(after):
        a, b = before.get(f), after.get(f)
        if (a is None) != (b is None):
            return True
        if a is not None and abs(a - b) > 1e-6 * max(1.0, abs(a)):
            return True
    return False


def first_fix(versions: list[dict], group: str):
    """The first step where nutrition error flags go from some to none, the per-100 values change and the new version still holds values for the group's fields.
    Returns (before, after) or None."""
    ordered = sorted(versions, key=lambda v: v["last_modified_t"])
    for before, after in zip(ordered, ordered[1:]):
        if not nutrition_errors(before) or nutrition_errors(after):
            continue
        if after.get("nutrition_per") != "100g" or not changed(values(before), values(after)):
            continue
        if not any(f in values(after) for f in akl.GROUP_FIELDS[group]):
            continue
        return before, after
    return None


def judge(card: dict, versions: list[dict]) -> dict:
    """One keyed card against its product's version history."""
    out = {"code": card["code"], "group": card["group"], "versions": len(versions)}
    fix = first_fix(versions, card["group"])
    if fix is None:
        return {**out, "status": "no_fix_found"}
    before, after = fix
    now = akl.matches_key_for_group(values(after), card["per100"], card["group"])
    then = akl.matches_key_for_group(values(before), card["per100"], card["group"])
    return {**out, "status": "fix_found", "fix_rev": after.get("rev"), "fix_at": after.get("last_modified_ts"), "compared": now["compared"], "wrong_after": now["wrong"],
            "agrees": now["match"], "agreed_before": then["match"]}


def load(review: Path = REVIEW, versions: str = "stg_silver_versions.jsonl"):
    cards, seen = {}, set()
    for name in KEY_FILES:
        for code, card in json.loads((review / name).read_text(encoding="utf8"))["cards"].items():
            if card.get("usable") and code not in seen:
                seen.add(code)
                cards[code] = card
    by_code: dict[str, list[dict]] = {}
    for line in (review / versions).read_text(encoding="utf8").splitlines():
        row = json.loads(line)
        by_code.setdefault(row["code"], []).append(row)
    return cards, by_code


def summarise(results: list[dict]) -> dict:
    fixed = [r for r in results if r["status"] == "fix_found" and r["compared"]]
    return {"keyed": len(results), "fix_found": len(fixed), "agree": sum(r["agrees"] for r in fixed),
            "agreed_before_the_fix": sum(r["agreed_before"] for r in fixed)}


def main() -> None:
    cards, by_code = load(versions=sys.argv[1] if len(sys.argv) > 1 else "stg_silver_versions.jsonl")
    results, skipped = [], {}
    for code, card in cards.items():
        if card.get("basis") != "per 100 g":
            skipped[card.get("basis")] = skipped.get(card.get("basis"), 0) + 1
            continue
        results.append(judge(card, by_code.get(code, [])))
    summary = summarise(results)
    print("keyed usable cards:", len(cards), "| skipped (basis is not per 100 g):", skipped)
    print("summary:", json.dumps(summary))
    for r in results:
        if r["status"] == "fix_found":
            print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
