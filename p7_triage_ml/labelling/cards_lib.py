"""Label cards for the unaided labelling gate (design 7.2, Phase D item 16). Pure Python: no network, no Databricks.

A card asks one question: does the nutrition record match the nutrition table printed on the pack? The cards come from OFF's nutrition-number flags that none of our
11 arithmetic rules decides (the scope of the labelling guide, section 5). Everything here is deterministic: the same candidate order and the same OFF answers give the
same cards, so nobody chose them by hand.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))        # rules_lib sits in the parent folder

# --- which flags are in scope -------------------------------------------------------------------------------------------------------------------
NUTRIENT_WORDS = {"salt": "Salt", "saturated-fat": "Saturated fat", "proteins": "Protein", "sugars": "Sugars", "carbohydrates": "Carbohydrates",
                  "fiber": "Fibre", "fat": "Fat", "energy": "Energy"}
_VERY = re.compile(r"^value-very-(high|low)-for-category-(" + "|".join(NUTRIENT_WORDS) + r")$")
_UNDER = re.compile(r"^value-under-(0-01|0-001)-g-salt$")
IDENTICAL = "3-or-more-values-are-identical"


def in_scope(family: str) -> bool:
    return bool(_VERY.match(family) or _UNDER.match(family) or family == IDENTICAL)


def plain_flag(family: str) -> str:
    """The flag in plain words, as the card shows it."""
    m = _VERY.match(family)
    if m:
        return f"{NUTRIENT_WORDS[m.group(2)]} is very {m.group(1)} for its category."
    m = _UNDER.match(family)
    if m:
        return "Salt is recorded as under " + m.group(1).replace("-", ".") + " g."
    if family == IDENTICAL:
        return "Three or more nutrition values are identical."
    raise ValueError(f"not an in-scope flag family: {family}")


# --- the photos ---------------------------------------------------------------------------------------------------------------------------------

def photo_urls(product: dict) -> dict | None:
    """From OFF's `selected_images`: the nutrition photo (large) and the front photo. None when the product has no selected nutrition photo, which makes it unusable
    for the gate. The large nutrition image replaces the `400` size in OFF's own display URL with `full`, so the table is readable."""
    sel = product.get("selected_images") or {}
    nut = (sel.get("nutrition") or {}).get("display") or {}
    if not nut:
        return None
    lang, url = sorted(nut.items())[0]
    front = (sel.get("front") or {}).get("display") or {}
    return {"nutrition_full": re.sub(r"\.400\.jpg$", ".full.jpg", url), "nutrition_400": url, "nutrition_lang": lang,
            "front": sorted(front.items())[0][1] if front else None}


# --- the card -----------------------------------------------------------------------------------------------------------------------------------
VALUE_ROWS = (("energy_kj", "Energy", "kJ"), ("energy_kcal", "Energy", "kcal"), ("fat", "Fat", "g"), ("saturated_fat", "Saturated fat", "g"),
              ("carbohydrates", "Carbohydrates", "g"), ("sugars", "Sugars", "g"), ("added_sugars", "Added sugars", "g"), ("starch", "Starch", "g"),
              ("fiber", "Fibre", "g"), ("proteins", "Protein", "g"), ("salt", "Salt", "g"), ("sodium", "Sodium", "g"))
BASIS = {"100g": "per 100 g", "100ml": "per 100 ml", "serving": "per serving"}
PREPARATION = {"as_sold": "as sold", "prepared": "as prepared"}


def _num(x: float) -> str:
    return f"{round(x, 3):.10g}"


def values_text(row: dict) -> str:
    lines = [f"{label}: {_num(row[key])} {unit}" for key, label, unit in VALUE_ROWS if row.get(key) is not None]
    return "\n".join(lines) if lines else "No nutrition values recorded."


def amount(value, unit) -> str:
    return "not recorded" if value is None else f"{_num(value)} {unit or ''}".strip()


def off_link(code: str) -> str:
    return f"https://world.openfoodfacts.org/product/{code}"


def make_task(row: dict, families: list[str], photos: dict, set_name: str, number: int) -> dict:
    """One Label Studio task. `row` is one product from product_history (latest period); `families` its in-scope flag families."""
    basis = BASIS.get(row.get("nutrition_per") or "", "basis not recorded")
    prep = PREPARATION.get(row.get("nutrition_preparation") or "", "")
    return {"data": {"card": f"{set_name} {number:02d}", "name": row.get("product_name") or "(no name)", "brand": row.get("brands") or "(no brand)",
                     "barcode": row["code"], "pack_size": amount(row.get("quantity_amount"), row.get("quantity_unit")),
                     "serving_size": amount(row.get("serving_amount"), row.get("serving_unit")),
                     "basis": (basis + (", " + prep if prep else "")), "flags": " ".join(plain_flag(f) for f in families),
                     "values": values_text(row), "link": off_link(row["code"]), "nutrition_photo": photos["nutrition_full"],
                     "nutrition_photo_small": photos["nutrition_400"], "front_photo": photos["front"] or photos["nutrition_400"],
                     "photo_languages": printed_languages(photos.get("ocr") or [])},
            "meta": {"set": set_name, "families": families, "code": row["code"], "ocr_languages": photos.get("ocr") or []}}


# --- the deterministic selection ----------------------------------------------------------------------------------------------------------------

def select(candidates: Iterable[dict], photos_for: Callable[[str], dict | None], n: int, cap: int, taken: set[str] | None = None) -> list[dict]:
    """Walk the candidates in the order given (the caller orders them by a hash of the barcode) and accept a product when it is not in `taken`, its first in-scope flag
    family has fewer than `cap` cards already, and `photos_for(code)` finds a nutrition photo. Stops at `n`. A candidate is a dict with `row` and `families`."""
    taken = set() if taken is None else taken
    per_family: dict[str, int] = {}
    out: list[dict] = []
    for cand in candidates:
        code = cand["row"]["code"]
        family = cand["families"][0]
        if code in taken or per_family.get(family, 0) >= cap:
            continue
        photos = photos_for(code)
        if not photos:
            continue
        per_family[family] = per_family.get(family, 0) + 1
        taken.add(code)
        out.append({**cand, "photos": photos})
        if len(out) == n:
            break
    return out


INFO_KEYS = (("l_name", "Product", "name"), ("l_brand", "Brand", "brand"), ("l_barcode", "Barcode", "barcode"), ("l_pack", "Pack size", "pack_size"),
             ("l_serving", "Serving size", "serving_size"), ("l_basis", "Record is", "basis"))
CALC_KEYS = ("c_kj_from_kcal", "c_energy_from_nutrients")
WINDOW = 0.10                                                          # guide F9: the pack agrees within 10% of its value or one step of its last digit


def _fmt(x: float) -> str:
    s = f"{round(x, 3):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _sig(x: float, n: int = 3) -> str:
    """A computed number with n (three) significant digits, never in exponent form: 0.0006, 0.152, 6.07, 111, 1,540."""
    if x == 0:
        return "0"
    digits = max(0, n - 1 - math.floor(math.log10(abs(x))))
    return f"{round(x, digits):.{digits}f}".rstrip("0").rstrip(".") if digits else f"{round(x):d}"


def _decimals(x: float) -> int:
    s = f"{round(x, 3):.3f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def window(value: float) -> str | None:
    """The range in which a pack value 'agrees' with this record value (guide F9, arithmetic only: no verdict). None for zero, where the pack must also say 0 or a '<' value."""
    if value == 0:
        return None
    step = 10.0 ** -_decimals(value)
    w = max(WINDOW * abs(value), step)
    return f"{_sig(value - w)} to {_sig(value + w)}"


def _serving(data: dict) -> tuple[float, str] | None:
    parts = (data.get("serving_size") or "").split()
    if len(parts) == 2 and parts[1] in ("g", "ml"):
        try:
            return float(parts[0]), parts[1]
        except ValueError:
            return None
    return None


def _numbers(data: dict) -> dict[str, tuple[float, str]]:
    shown = {}
    for line in data["values"].splitlines():
        label, _, value = line.partition(": ")
        if value:
            num, unit = value.split()
            shown[(label, unit)] = (float(num), unit)
    return {key: shown[(label, unit)] for key, label, unit in VALUE_ROWS if (label, unit) in shown}


def card_lines(data: dict) -> dict:
    """The card as one short line per fact, each in its own task field, for Label Studio's Header tags (shown in the theme's own colour: white on the dark theme). Custom HTML
    ignored the dark theme and the Table tag paged the numbers, so neither is used. A nutrient the record does not have reads 'not recorded', so every card has the same lines.
    Each nutrient line carries the arithmetic the labeller would otherwise do by hand, and nothing else: the window in which a pack value agrees (F9), the value for one gram or ml
    (times the serving size printed on the pack, it gives the pack's per-serving figure), the value per serving when the record has one (F1 in reverse) and the units (F7), each
    mg figure beside the gram figure it converts. There is no verdict anywhere: the labeller reads the pack and decides."""
    out = {key: f"{label}: {data[field]}" for key, label, field in INFO_KEYS}
    nums = _numbers(data)
    serving = _serving(data)
    per1 = "ml" if str(data.get("basis", "")).startswith("per 100 ml") else "g"
    for key, label, unit in VALUE_ROWS:
        name = label
        if key not in nums:
            out[f"v_{key}"] = f"{name}: not recorded"
            continue
        v, _ = nums[key]
        win = window(v)
        mass = key in ("salt", "sodium")                                  # packs print salt and sodium in mg: each mg figure sits beside the g figure it converts
        bits = [f"pack agrees if {win} {unit}" if win else "pack agrees if it says 0, a trace or a '<' value"]
        bits.append(f"per 1 {per1}: {_sig(v / 100, 4)} {unit}")
        if serving:
            part = v * serving[0] / 100
            bits.append(f"per {_fmt(serving[0])} {serving[1]} serving: {_sig(part)} {unit}" + (f" = {_sig(part * 1000)} mg" if mass else ""))
        out[f"v_{key}"] = f"{name}: {_fmt(v)} {unit}" + (f" = {_sig(v * 1000)} mg" if mass else "") + f"   ({'; '.join(bits)})"
    out["c_kj_from_kcal"] = ""
    out["c_energy_from_nutrients"] = ""
    if "energy_kcal" in nums:
        out["c_kj_from_kcal"] = f"kJ from the kcal figure (4.184 x kcal): {_sig(4.184 * nums['energy_kcal'][0])} kJ"
    else:
        out["c_kj_from_kcal"] = "kJ from the kcal figure: no kcal recorded"
    import rules_lib
    n = {name: nums[key][0] for key, name in RULE_KEYS.items() if key in nums and key != "energy_kj" and key != "energy_kcal"}
    kj, kcal = rules_lib.computed_energy(n, "kj"), rules_lib.computed_energy(n, "kcal")
    out["c_energy_from_nutrients"] = ("Energy from the nutrients (OFF factors): " + f"{_sig(kj)} kJ / {_sig(kcal)} kcal") if kj is not None else "Energy from the nutrients: carbohydrates, fat or protein missing"
    return out


# --- the nutrient words of the photo's language --------------------------------------------------------------------------------------------------
# One line per term, in each language OFF's text scan found on the nutrition photo (see ocr_languages). Words only, no numbers and no verdict: the labeller reads the pack
# and decides. The scan is a detection, so the card says it was found by a text scan.
GLOSSARY_TERMS = ("energy", "fat", "saturated", "carbs", "sugars", "fibre", "protein", "salt", "sodium", "per100", "serving")
GLOSSARY_NAMES = {"en": "English", "fr": "French", "de": "German", "nl": "Dutch", "es": "Spanish", "it": "Italian", "pl": "Polish", "pt": "Portuguese", "sv": "Swedish",
                  "da": "Danish", "uk": "Ukrainian", "ru": "Russian", "cs": "Czech", "bg": "Bulgarian"}
GLOSSARY = {
    "fr": ("valeur énergétique, énergie", "matières grasses, lipides", "dont acides gras saturés", "glucides", "dont sucres", "fibres alimentaires",
           "protéines", "sel", "sodium", "pour 100 g / 100 ml", "par portion"),
    "de": ("Brennwert, Energie", "Fett", "davon gesättigte Fettsäuren", "Kohlenhydrate", "davon Zucker", "Ballaststoffe", "Eiweiß", "Salz", "Natrium",
           "pro 100 g / 100 ml", "pro Portion"),
    "nl": ("energie", "vetten", "waarvan verzadigde vetzuren", "koolhydraten", "waarvan suikers", "vezels", "eiwitten", "zout", "natrium", "per 100 g / 100 ml", "per portie"),
    "es": ("valor energético, energía", "grasas", "de las cuales saturadas", "hidratos de carbono", "de los cuales azúcares", "fibra alimentaria", "proteínas", "sal", "sodio",
           "por 100 g / 100 ml", "por ración"),
    "it": ("energia, valore energetico", "grassi", "di cui acidi grassi saturi", "carboidrati", "di cui zuccheri", "fibre", "proteine", "sale", "sodio", "per 100 g / 100 ml",
           "per porzione"),
    "pl": ("wartość energetyczna", "tłuszcz", "w tym kwasy tłuszczowe nasycone", "węglowodany", "w tym cukry", "błonnik", "białko", "sól", "sód", "na 100 g / 100 ml", "na porcję"),
    "pt": ("valor energético, energia", "lípidos, gorduras", "dos quais saturados", "hidratos de carbono", "dos quais açúcares", "fibra", "proteínas", "sal", "sódio",
           "por 100 g / 100 ml", "por dose, por porção"),
    "sv": ("energi", "fett", "varav mättat fett", "kolhydrater", "varav sockerarter", "fiber", "protein", "salt", "natrium", "per 100 g / 100 ml", "per portion"),
    "da": ("energi", "fedt", "heraf mættede fedtsyrer", "kulhydrat", "heraf sukkerarter", "kostfibre", "protein", "salt", "natrium", "pr. 100 g / 100 ml", "pr. portion"),
    "uk": ("енергетична цінність", "жири", "з них насичені", "вуглеводи", "з них цукри", "харчові волокна", "білки", "сіль", "натрій", "на 100 г / 100 мл", "на порцію"),
    "cs": ("energetická hodnota", "tuky", "z toho nasycené mastné kyseliny", "sacharidy", "z toho cukry", "vláknina", "bílkoviny", "sůl", "sodík", "na 100 g / 100 ml", "na porci"),
    "bg": ("енергийна стойност", "мазнини", "от които наситени", "въглехидрати", "от които захари", "фибри, хранителни влакна", "протеини, белтъчини", "сол", "натрий",
           "на 100 г / 100 мл", "на порция"),
    "ru": ("энергетическая ценность", "жиры", "в том числе насыщенные", "углеводы", "в том числе сахара", "пищевые волокна", "белки", "соль", "натрий", "на 100 г / 100 мл",
           "на порцию"),
}
GLOSSARY_LABELS = ("Energy", "Fat", "Saturated fat", "Carbohydrates", "Sugars", "Fibre", "Protein", "Salt", "Sodium", "Per 100 g or 100 ml", "Per serving")
GLOSSARY_KEYS = tuple(f"g_{term}" for term in GLOSSARY_TERMS)


MIN_KEEP, MIN_SHOW, MAX_SHOW = 0.25, 0.10, 3        # a card needs a listed language at 25%; the card shows listed languages at 10%, three at most


def supported(code: str) -> bool:
    return code == "en" or code in GLOSSARY


def ocr_languages(ocr: dict) -> list[tuple[str, float]]:
    """The languages OFF's text scan (Google Vision, kept by OFF next to each photo) detected on the page, most likely first. The scan is a detection with a confidence, not a
    certainty: it found the main language on most test photos, but named Hungarian, Slovak and Slovene on a pack that prints German, French and Italian."""
    found: dict[str, float] = {}
    for r in ocr.get("responses") or []:
        for page in ((r.get("fullTextAnnotation") or {}).get("pages") or []):
            for d in (page.get("property") or {}).get("detectedLanguages") or []:
                found[d["languageCode"]] = max(found.get(d["languageCode"], 0.0), float(d.get("confidence", 0)))
    return sorted(found.items(), key=lambda kv: -kv[1])


def readable(langs: list) -> bool:
    """A card is kept only if the photo has at least one language the word lists cover. A multilingual pack repeats every term in each language, so one is enough."""
    return any(supported(code) and conf >= MIN_KEEP for code, conf in langs)


def printed_languages(langs: list) -> list[str]:
    return [code for code, conf in langs if supported(code) and conf >= MIN_SHOW][:MAX_SHOW]


def glossary_lines(data: dict) -> dict:
    """g_title, g_note and one g_<term> line each, for the Header tags under the photo. Words only, no numbers and no verdict. The lines are the words of every listed language the
    text scan found on the photo, joined by ' / ', then the English meaning. The same lines on every card."""
    codes = data.get("photo_languages") or []
    others = [c for c in codes if c != "en"]
    names = ", ".join(GLOSSARY_NAMES.get(c, c) for c in codes) or "none found"
    out = {"g_title": f"Words on the pack. Languages found on the photo: {names}"}
    if not others:
        out["g_note"] = "English: no translation needed." if codes else "No listed language found on this photo."
    else:
        out["g_note"] = "Found by a text scan, so check it against the pack." + (" English is printed as well." if "en" in codes else "")
    for n, (key, label) in enumerate(zip(GLOSSARY_KEYS, GLOSSARY_LABELS)):
        words = " / ".join(GLOSSARY[c][n] for c in others) if others else label.lower()
        out[key] = f"{words} = {label}"
    return out


# --- the record the labeller sees must be one our arithmetic rules do not already decide ---------------------------------------------------------
RULE_KEYS = {"energy_kj": "energy-kj", "energy_kcal": "energy-kcal", "fat": "fat", "saturated_fat": "saturated-fat", "carbohydrates": "carbohydrates", "sugars": "sugars",
             "starch": "starch", "fiber": "fiber", "proteins": "proteins", "salt": "salt", "sodium": "sodium"}


def rule_violations(row: dict) -> list[str]:
    """The 11 rules of rules_lib run on the numbers the card shows. The gold rule verdicts cover only input sets that OFF itself checks, so a record whose basis is
    missing (per 100 g impossible to know) can show a value over 100 g without any verdict row. The card must not show such a record: the guide says rules decide those."""
    import rules_lib
    numbers = {name: row[key] for key, name in RULE_KEYS.items() if row.get(key) is not None}
    return [name for name, v in rules_lib.verdicts(numbers).items() if v.status == "violated"]


def usable_record(row: dict) -> bool:
    return row.get("nutrition_per") in ("100g", "100ml") and not rule_violations(row)
