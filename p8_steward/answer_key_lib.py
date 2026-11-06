"""Reading the answer key (item 23): what the owner types for one card, as one line, becomes numbers.

The owner types what the pack says on ONE line, for example

    kcal 168, kj 701, fat 9.7, sat 1.7, carbs 0, sugars 0, fibre 0, protein 20.1, salt 2.55, sodium 445mg

Rules (so the owner never converts by hand and never fights a number box):
  - a word and a number, separated by a space or '=' or ':'; entries are separated by semicolons, line breaks, or a comma that is followed by a word;
  - the number may use a comma or a point as its decimal sign, with or without a leading 0 (`.5`, `0,5`, `0.045`);
  - a unit may follow: `mg` and `g` for the mass nutrients (stored in grams, so `445mg` becomes 0.445), `ug` or `mcg` (micrograms), `kj` and `kcal` are the field's own unit;
  - a leading `<`, `~` or `<=` marks the figure as approximate (the pack printed `<0.5 g`): the number is kept and the field is listed in `approx`;
  - energy is `kcal` and `kj` (kJ); the other words are fat, sat, carbs, sugars, fibre, protein, salt, sodium (a few spellings of each are accepted);
  - a word that is not recognised is reported in `errors`; it never silently disappears.
Energy fields are kcal and kJ, everything else grams.
"""
from __future__ import annotations

import re

ALIASES = {
    "energy_kcal": ("kcal", "cal", "calories", "energy kcal"),
    "energy_kj": ("kj", "energy kj"),
    "fat": ("fat", "fats", "lipids"),
    "saturated_fat": ("sat", "sat fat", "saturated", "saturates", "saturated fat"),
    "carbohydrates": ("carbs", "carb", "carbohydrate", "carbohydrates"),
    "sugars": ("sugar", "sugars"),
    "fiber": ("fibre", "fiber", "dietary fibre", "dietary fiber"),
    "proteins": ("protein", "proteins", "prot"),
    "salt": ("salt",),
    "sodium": ("sodium", "na"),
}
WORD = {a: field for field, names in ALIASES.items() for a in names}
MASS_TO_G = {"": 1.0, "g": 1.0, "mg": 1e-3, "ug": 1e-6, "mcg": 1e-6, "µg": 1e-6}
ENERGY = {"energy_kcal", "energy_kj"}
ENTRY = re.compile(r"^\s*(?P<word>[A-Za-z][A-Za-z ]*?)\s*[=:\s]\s*(?P<approx>(?:<=|<|~|≈)\s*)?(?P<num>\d*[.,]?\d+|\d+[.,])\s*(?P<unit>[A-Za-zµ]*)\s*$")


def parse(text: str) -> dict:
    """{'values': {field: number}, 'approx': [field], 'errors': [str]} for one typed line."""
    out = {"values": {}, "approx": [], "errors": []}
    for chunk in re.split(r"[;\n]+|,(?=\s*[A-Za-z<~≈])", text or ""):      # a comma separates entries only when a word (or a < ~ sign) follows; between digits it is a decimal sign
        if not chunk.strip():
            continue
        m = ENTRY.match(chunk)
        if not m:
            out["errors"].append(f"cannot read: {chunk.strip()!r}")
            continue
        word, unit = re.sub(r"\s+", " ", m.group("word").strip().lower()), m.group("unit").lower()
        field = WORD.get(word)
        if field is None:
            out["errors"].append(f"unknown word: {word!r}")
            continue
        number = float(m.group("num").replace(",", "."))
        if field in ENERGY:
            if unit not in ("", "kcal" if field == "energy_kcal" else "kj"):
                out["errors"].append(f"{word}: unit {unit!r} does not fit the field")
                continue
        else:
            if unit not in MASS_TO_G:
                out["errors"].append(f"{word}: unknown unit {unit!r}")
                continue
            number = round(number * MASS_TO_G[unit], 9)
        if field in out["values"]:
            out["errors"].append(f"{word}: given twice")
            continue
        out["values"][field] = number
        if m.group("approx"):
            out["approx"].append(field)
    return out


BOX_NAMES = {"k_energy_kcal": "energy_kcal", "k_energy_kj": "energy_kj", "k_fat": "fat", "k_saturated_fat": "saturated_fat", "k_carbohydrates": "carbohydrates",
             "k_sugars": "sugars", "k_fiber": "fiber", "k_proteins": "proteins", "k_salt": "salt", "k_sodium": "sodium", "k_sodium_mg": "sodium", "k_sodium_unit": "sodium"}
# The test form (project 38 on) has its sodium box in MILLIGRAMS: a bare number there is mg. The older box `k_sodium` (projects 36 and 37) keeps grams as its default, so re-reading those
# projects never changes meaning. An explicit unit is always respected ('0.445g' in the mg box is 0.445 g).
BOX_DEFAULT_UNIT = {"k_sodium_mg": "mg"}
# The fresh sealed set (project on from 2026-11-06) has its sodium box with NO default: a bare number there is refused (the card is listed as unreadable by make_answer_key.py until the owner adds mg or g).
# Two keys of the first sealed test were wrong because the mg default hid a printed g.
REQUIRE_UNIT = {"k_sodium_unit"}
BARE_NUMBER = re.compile(r"^\s*(?:<=|<|~|≈)?\s*(?:\d*[.,]?\d+|\d+[.,])\s*$")


def with_default_unit(box: str, text: str) -> str:
    """The typed text with the box's default unit appended when only a number was typed ('445' in the sodium box becomes '445mg')."""
    unit = BOX_DEFAULT_UNIT.get(box)
    return f"{(text or '').strip()}{unit}" if unit and BARE_NUMBER.match(text or "") else (text or "")


def parse_box(field: str, text: str) -> dict:
    """What was typed in ONE box (a number, optionally with a unit and a leading < or ~), read for the field the box belongs to: '445mg' in the sodium box is 0.445."""
    word = ALIASES[field][0]
    r = parse(f"{word} {(text or '').strip()}") if (text or "").strip() else {"values": {}, "approx": [], "errors": []}
    return r


def parse_boxes(answers: dict) -> dict:
    """{box name (k_sodium, ...): typed text} -> the same result as parse() for the whole card."""
    out = {"values": {}, "approx": [], "errors": []}
    for name, text in answers.items():
        field = BOX_NAMES.get(name)
        if field is None:
            continue
        if name in REQUIRE_UNIT and BARE_NUMBER.match(text or ""):
            out["errors"].append(f"{name}: a unit (mg or g) is required, not a bare number")
            continue
        r = parse_box(field, with_default_unit(name, text))
        out["values"].update(r["values"])
        out["approx"] += r["approx"]
        out["errors"] += [f"{name}: {e}" for e in r["errors"]]
    return out


def format_line(values: dict) -> str:
    """The same line from numbers (used to carry earlier answers over): grams and kcal / kJ as they are."""
    short = {"energy_kcal": "kcal", "energy_kj": "kj", "fat": "fat", "saturated_fat": "sat", "carbohydrates": "carbs", "sugars": "sugars", "fiber": "fibre",
             "proteins": "protein", "salt": "salt", "sodium": "sodium"}
    parts = []
    for field in ALIASES:
        if values.get(field) is not None:
            v = values[field]
            parts.append(f"{short[field]} {v:.10g}")
    return ", ".join(parts)


SERVING = re.compile(r"^\s*(?P<num>\d*[.,]?\d+)\s*(?P<unit>g|ml)\s*$", re.IGNORECASE)


def parse_serving(text: str) -> tuple[float, str] | None:
    """A serving size typed as '30g', '15 ml' or '2,7 g' -> (amount, unit); anything else ('1 bottle', '14g and 25g', '') -> None."""
    m = SERVING.match(text or "")
    return (float(m.group("num").replace(",", ".")), m.group("unit").lower()) if m else None


BRACKET_SERVING = re.compile(r"\(\s*(?P<num>\d*[.,]?\d+)\s*(?P<unit>g|ml)\s*\)", re.IGNORECASE)


def parse_bracket_serving(text: str) -> tuple[float, str] | None:
    """A serving size a pack prints with a household measure first, '1/4 Cup (30g)' or '1 bottle (330 ml)' -> the amount in brackets. Used ONLY for a model's reading of the
    scan text: the owner's typed answers keep the strict rule above, so the key never changes meaning."""
    m = BRACKET_SERVING.search(text or "")
    return (float(m.group("num").replace(",", ".")), m.group("unit").lower()) if m else None


def key_entry(task: dict) -> dict:
    """One answer-key entry from an exported task: the owner's numbers as per-100 values when the pack allows it, else the plain reason it cannot be used.

    usable only when the basis is per 100 g or per 100 ml, or per serving with a serving size in g or ml (then every number is scaled to 100). Nothing is guessed:
    a card marked 'cannot read', or per serving with a serving size that is not in g or ml, is kept with its reason and left out of scoring.
    """
    data, results = task["data"], task["annotations"][0]["result"]
    basis = next((r["value"]["choices"][0] for r in results if r["from_name"] == "basis"), None)
    boxes = {r["from_name"]: r["value"]["text"][0] for r in results if r["from_name"].startswith("k_")}
    serving_text = next((r["value"]["text"][0] for r in results if r["from_name"] == "serving_size"), "")
    note = next((r["value"]["text"][0] for r in results if r["from_name"] == "note"), "")
    flags = " ".join(c for r in results if r["from_name"] == "pack_flags" for c in r["value"].get("choices", []))
    parsed = parse_boxes(boxes)
    entry = {"code": data["code"], "group": data.get("group"), "basis": basis, "serving": serving_text, "note": note, "approx": parsed["approx"], "errors": parsed["errors"],
             "usable": False, "reason": None, "per100": {}, "unit": None, "misprint": "misprints" in flags}
    if parsed["errors"]:
        entry["reason"] = "a box could not be read: " + "; ".join(parsed["errors"])
    elif "unreadable" in flags:
        entry["reason"] = "a flagged number is unreadable on the photo (the owner's tick)"
    elif basis == "cannot read the table" or not basis:
        entry["reason"] = "the owner could not read the table"
    elif not parsed["values"]:
        entry["reason"] = "no numbers were typed"
    elif basis in ("per 100 g", "per 100 ml"):
        entry.update(usable=True, per100=parsed["values"], unit="g" if basis == "per 100 g" else "ml")
    elif basis.startswith("per serving"):
        serving = parse_serving(serving_text)
        if serving is None:
            entry["reason"] = f"per serving only and the serving size {serving_text!r} is not in g or ml"
        else:
            factor = 100.0 / serving[0]
            entry.update(usable=True, per100={f: round(v * factor, 6) for f, v in parsed["values"].items()}, unit=serving[1])
    else:
        entry["reason"] = f"unknown basis {basis!r}"
    return entry


def build_key(export: list[dict]) -> dict:
    """{code: key_entry} for every answered task of an export, plus nothing else; unanswered tasks are left out."""
    return {t["data"]["code"]: key_entry(t) for t in export if t.get("annotations")}


TOLERANCE = {"energy_kcal": (0.10, 2.0), "energy_kj": (0.10, 8.0)}      # (relative, smallest absolute allowance); every other field is grams: (0.10, 0.05)


def field_matches(field: str, value: float | None, truth: float) -> bool:
    """A value is right when it is within 10% of what the pack says, or within a small absolute allowance (so 0.0 against 0.04 is not an error)."""
    if value is None:
        return False
    rel, floor = TOLERANCE.get(field, (0.10, 0.05))
    return abs(value - truth) <= max(rel * abs(truth), floor)


def matches_key(record: dict, per100: dict) -> dict:
    """Compare a record (per-100 values) with the answer key. Only fields present in BOTH are compared: a field the record does not carry cannot be repaired by
    changing a value. Returns {'compared': n, 'wrong': [fields], 'match': bool (True when at least one field was compared and none is wrong)}."""
    compared = [f for f in per100 if record.get(f) is not None]
    wrong = [f for f in compared if not field_matches(f, record[f], per100[f])]
    return {"compared": len(compared), "wrong": wrong, "match": bool(compared) and not wrong}


# The fields a flag group is about (the same ones the owner was asked to type for it). A repair is judged on THESE fields: a record can differ from the pack on a field
# no flag concerns, and a fix for the flagged problem is neither right nor wrong about that.
GROUP_FIELDS = {
    "A_energy_mismatch": ("energy_kcal", "energy_kj", "fat", "carbohydrates", "proteins"),
    "B_salt_vs_sodium": ("salt", "sodium"),
    "C_values_too_large": tuple(ALIASES),
    "D_sums_too_large": ("fat", "saturated_fat", "carbohydrates", "sugars"),
    "E_other_nutrition": tuple(ALIASES),
}


def matches_key_for_group(record: dict, per100: dict, group: str) -> dict:
    """matches_key restricted to the fields the flag group is about."""
    fields = GROUP_FIELDS[group]
    return matches_key(record, {f: v for f, v in per100.items() if f in fields})


def reading_to_per100(reading: dict) -> dict:
    """A model's reading of a pack's text ({'basis', 'serving_size', 'values_per_100': {field: number}}) as per-100 values, by the same rules as key_entry: per 100 g or ml as
    read, per serving only scaled by a serving size in g or ml, anything else (unclear, no serving size) not usable. Unknown fields and non-numbers are dropped, never kept."""
    basis = str(reading.get("basis") or "")
    raw = reading.get("values_per_100") or {}
    values = {f: float(v) for f, v in raw.items() if f in ALIASES and isinstance(v, (int, float)) and not isinstance(v, bool)}
    out = {"usable": False, "per100": {}, "reason": None}
    if not values:
        out["reason"] = "no numbers read"
    elif basis in ("per 100 g", "per 100 ml"):
        out.update(usable=True, per100=values)
    elif basis.startswith("per serving"):
        serving = parse_serving(str(reading.get("serving_size") or "")) or parse_bracket_serving(str(reading.get("serving_size") or ""))
        if serving is None:
            out["reason"] = "per serving only and no serving size in g or ml"
        else:
            out.update(usable=True, per100={f: round(v * 100.0 / serving[0], 6) for f, v in values.items()})
    else:
        out["reason"] = f"basis {basis!r} is not usable"
    return out


NUMBER_TOKEN = re.compile(r"\d+(?:[.,\-]\d+)*")


def numbers_in_text(text: str) -> set[float]:
    """Every number a scan text could be printing, in the forms a pack uses: '9.8', '9,8' and '9-8' (a dash or comma between digits can be a decimal point), '2.307' or '2,307'
    as a thousands separator (also read as 2307), and plain integers. Used to check that a model's value is printed on the pack and not invented."""
    found: set[float] = set()
    for grouped in re.finditer(r"(?<!\d)\d{1,3}(?: \d{3})+(?:[.,]\d+)?(?!\d)", text or ""):                     # '3 437.8' : a space as the thousands mark
        found.add(float(grouped.group(0).replace(" ", "").replace(",", ".")))
    for token in NUMBER_TOKEN.findall(text or ""):
        parts = re.split(r"[.,\-]", token)
        found.add(float(parts[0] + "." + "".join(parts[1:])) if len(parts) > 1 else float(parts[0]))      # a separator as a decimal point
        found.add(float("".join(parts)))                                                                    # a separator as a thousands mark, or no separator
        if len(parts) == 2:
            found.add(float(parts[0]))                                                                      # the integer part alone (a dropped decimal)
    return found


def grounded_values(values: dict, text: str) -> tuple[dict, list[str]]:
    """Split a reading's values into those printed in the text and those that are not. A value counts as printed when it equals a number in the text, or 1000 times a number
    in the text for the gram fields (a figure printed in mg and converted). Energy fields are never scaled. Returns (kept, dropped field names)."""
    nums = numbers_in_text(text)

    def present(x: float) -> bool:
        return any(abs(x - n) <= 1e-6 * max(1.0, abs(n)) for n in nums)

    kept, dropped = {}, []
    for field, v in values.items():
        ok = present(v) or (field not in ENERGY and present(round(v * 1000.0, 6)))
        (kept.__setitem__(field, v) if ok else dropped.append(field))
    return kept, dropped


ENERGY_WORDS = re.compile(r"kcal|kj|energ|calor|valor\s+energ|brennwert|nutri|nahrw|valeur|n[aä]hr|declaraci", re.IGNORECASE)


def text_has_table(text: str) -> bool:
    """A cheap check that the scan text holds a nutrition table at all: an energy or nutrition word and at least six numbers. A text without one is never sent to a model
    and never produces a proposal (the agent abstains)."""
    return bool(ENERGY_WORDS.search(text or "")) and len(re.findall(r"\d+(?:[.,]\d+)?", text or "")) >= 6
