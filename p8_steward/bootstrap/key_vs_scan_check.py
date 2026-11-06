"""Pre-run check of a sealed part's answer key against the scan text ALONE (A121 paragraph 11 (c)). No model is called, no tokens are spent, and no keyed value is printed:
it names the card and the reason, and the owner settles each warning on the photo.

  python p8_steward/bootstrap/key_vs_scan_check.py --part test2

What it looks for (only things the scan text can show; the photo has the last word):
  basis      the key says per 100 g / ml but the scan has a per-serving header and no per-100 header, or the key says per serving only but the scan prints a per-100 column
  unit       a keyed mass value that equals a printed number but whose printed unit differs from the unit the key implies (printed 'g' keyed as mg, printed 'mg' keyed as g)
  absent     a keyed mass or energy value that is printed nowhere in the scan (OCR may have missed it, or a typo or unit slip)
  range      salt or sodium above 30 g in 100 g, or a macro nutrient total above 105 g in 100 g (the pack may really print it: the owner confirms)
Needs the raw scans of the part (fetch_ocr_json.py --part <part> --only-usable) and the key (make_answer_key.py, run by the owner).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_key_lib as ak  # noqa: E402

SET = ROOT / "output" / "review_set"
MASS = ("fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt", "sodium")
PER_SERVING = re.compile(r"per\s*serv|per\s*portion|serving\s*size|per\s*pack", re.IGNORECASE)
PER_100 = re.compile(r"(?:per|pour|por|je)?\s*100\s*(?:g|gm|gram|ml|m1)\b|100g|100ml", re.IGNORECASE)
UNIT_AFTER = re.compile(r"^\s*(mg|g|gm|mcg|µg|ug)\b", re.IGNORECASE)


def printed_units(text: str, number: float) -> list[str]:
    """The unit words ('mg', 'g', or '' when none or unreadable) that follow each place where `number` is printed in the text (a dash or comma may be a decimal point)."""
    out = []
    for m in re.finditer(r"(?<![\d.,\-])(\d+(?:[.,\-]\d+)?)", text or ""):
        raw = m.group(1)
        try:
            val = float(re.sub(r"[,\-]", ".", raw))
        except ValueError:
            continue
        if abs(val - number) <= 1e-6 * max(1.0, abs(number)):
            u = UNIT_AFTER.match((text or "")[m.end():m.end() + 6])
            out.append({"gm": "g", "ug": "mcg", "µg": "mcg"}.get(u.group(1).lower(), u.group(1).lower()) if u else "")
    return out


def check_card(entry: dict, text: str) -> list[str]:
    """Warnings for one usable key entry against its scan text (empty list when nothing looks off)."""
    warns = []
    basis, per100 = entry.get("basis") or "", entry.get("per100") or {}
    has_serving, has_100 = bool(PER_SERVING.search(text)), bool(PER_100.search(text))
    if basis in ("per 100 g", "per 100 ml") and has_serving and not has_100:
        warns.append("basis: keyed as per 100 but the scan shows a per-serving header and no per-100 header")
    if basis.startswith("per serving") and has_100:
        warns.append("basis: keyed as per serving only but the scan prints a per-100 column")
    serving = ak.parse_serving(entry.get("serving") or "")
    factor = (serving[0] / 100.0) if basis.startswith("per serving") and serving else 1.0     # per-100 key value -> the value as typed (per serving)
    for f in MASS:
        if f not in per100:
            continue
        typed_g = per100[f] * factor                                    # grams as typed (the box converted mg to g)
        as_g, as_mg = printed_units(text, typed_g), printed_units(text, typed_g * 1000.0)
        if not as_g and not as_mg:
            warns.append(f"absent: the {f} value is printed nowhere in the scan text")
        elif as_g and "mg" in as_g and not any(u in ("g", "") for u in as_g):
            warns.append(f"unit: the {f} value is keyed in grams but the scan prints it in mg")
        elif as_mg and not as_g and "g" in as_mg and "mg" not in as_mg:
            warns.append(f"unit: the {f} value is keyed in mg but the scan prints it in g")
    for f in ("energy_kcal", "energy_kj"):
        if f in per100 and per100[f] * factor and not printed_units(text, per100[f] * factor):
            warns.append(f"absent: the {f} value is printed nowhere in the scan text")
    if max(per100.get("salt", 0), per100.get("sodium", 0)) > 30:
        warns.append("range: salt or sodium above 30 g in 100 g (a real pack may print it: confirm on the photo)")
    if sum(per100.get(f, 0) for f in ("fat", "carbohydrates", "proteins")) > 105:
        warns.append("range: fat, carbohydrates and protein together above 105 g in 100 g")
    return warns


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    a = ap.parse_args()
    key = json.loads((SET / f"answer_key_{a.part}_key.json").read_text(encoding="utf-8"))["cards"]
    export_files = sorted(SET.glob(f"answer_key_{a.part}_export_project*.json"))
    pos, tid = {}, {}
    if export_files:
        for i, t in enumerate(json.loads(export_files[-1].read_text(encoding="utf-8")), 1):
            pos[t["data"]["code"]], tid[t["data"]["code"]] = i, t["id"]
    missing, flagged, clean = [], 0, 0
    for code, entry in key.items():
        if not entry["usable"]:
            continue
        f = SET / "ocr_json" / f"{code}.json"
        if not f.exists() or f.stat().st_size <= 2:
            missing.append(code)
            continue
        import scan_layout as sl
        text = sl.rows_text(json.loads(f.read_text(encoding="utf-8")))
        warns = check_card(entry, text)
        if warns:
            flagged += 1
            print(f"card {pos.get(code, '?')} (task id {tid.get(code, '?')}): " + " | ".join(warns))
        else:
            clean += 1
    print(f"\n{flagged} cards with a warning, {clean} without; {len(missing)} usable cards have no scan yet" + (f" (run fetch_ocr_json.py --part {a.part} --only-usable)" if missing else ""))


if __name__ == "__main__":
    main()
