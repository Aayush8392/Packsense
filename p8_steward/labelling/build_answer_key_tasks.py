"""Builds the Label Studio tasks for the steward's ANSWER KEY (item 23): one task per product of the review set that has a nutrition photo.

  python p8_steward/labelling/build_answer_key_tasks.py --part dev|test --out output/review_set/answer_key_dev.json

A task shows ONLY the photo (as an embedded image, so nothing is fetched while labelling), the product's name and barcode, the flag in plain words and which nutrients to
type. It never carries the stored values or any proposal: the answer key must come from the pack alone. The tasks come in a fixed order, by a hash of the barcode, so a
longer list always starts with the same cards. Nothing is written outside output/ (gitignored).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "output" / "review_set"
sys.path.insert(0, str(ROOT / "p7_triage_ml" / "labelling"))
import cards_lib as cl  # noqa: E402     (the gate's word lists and its reading of OFF's text scan)

AGENT = "packsense-review-set/1 (private research use)"
PACE = 4.0          # seconds between requests to Open Food Facts (it refused connections at 1.5)

FIELDS_TO_TYPE = {
    "A_energy_mismatch": "energy (kcal and kJ), fat, carbohydrates and protein",
    "B_salt_vs_sodium": "salt and sodium",
    "C_values_too_large": "every nutrient printed in the table (energy, fat, saturated fat, carbohydrates, sugars, protein, salt, sodium)",
    "D_sums_too_large": "fat, saturated fat, carbohydrates and sugars",
    "E_other_nutrition": "every nutrient printed in the table",
}
FLAG_WORDS = [
    ("energy-value-in-kcal-does-not-match-value-in-kj", "the kcal figure and the kJ figure disagree"),
    ("does-not-match-value-computed-from-other-nutrients", "the energy figure disagrees with what fat, protein and carbohydrates add up to"),
    ("salt-does-not-match-sodium", "salt and sodium disagree"),
    ("value-total-over-105", "the nutrients together add up to more than 105 g in 100 g"),
    ("value-over-105", "a nutrient is listed as more than 105 g in 100 g"),
    ("over-3800-energy", "energy is listed as impossibly high"),
    ("greater-than", "a part is listed as larger than its total"),
]


def flag_text(flags: list[str]) -> str:
    out = []
    for f in flags:
        if not f.startswith("en:nutrition-"):
            continue
        words = next((w for key, w in FLAG_WORDS if key in f), f.replace("en:nutrition-", "").replace("-", " "))
        if words not in out:
            out.append(words)
    return "; ".join(out) or "a nutrition value"


def _get_json(url: str) -> dict:
    for attempt in range(2):                         # one retry after a pause for a refused or dropped connection; a quota answer is not retried
        time.sleep(PACE if attempt == 0 else 15)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
                raw = r.read()
            if raw[:2] == bytes([0x1f, 0x8b]):          # some scan files are stored gzipped and served as they are
                raw = gzip.decompress(raw)
            return json.loads(raw)
        except (urllib.error.HTTPError, ValueError):
            return {}
        except (urllib.error.URLError, TimeoutError):
            continue
    raise SystemExit(f"Open Food Facts did not answer for {url.split('?')[0]}; run again later (answers so far are cached)")


def photo_languages(codes: list[str]) -> dict[str, list[str]]:
    """The languages OFF's own text scan found on each product's nutrition photo (the gate's method), cached in output/review_set/ocr_languages.json.
    One small API reply and one small scan file per product, 1.5 seconds apart. A product with no scan gets an empty list."""
    cache_file = SET / "ocr_languages.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    for code in codes:
        if code in cache:
            continue
        product = _get_json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images,images").get("product") or {}
        photos = cl.photo_urls(product) if product else None
        ocr = []
        if photos:
            m = re.search(r"/products/(.+)/nutrition_([a-z]+)\.\d+\.", photos["nutrition_full"])
            imgid = ((product.get("images") or {}).get(f"nutrition_{m.group(2)}") or {}).get("imgid") if m else None
            if imgid:
                scan = _get_json(f"https://images.openfoodfacts.org/images/products/{m.group(1)}/{imgid}.json")
                ocr = [[c, round(p, 3)] for c, p in cl.ocr_languages(scan)] if scan else []
        cache[code] = cl.printed_languages(ocr)
        cache_file.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def build(part: str) -> list[dict]:
    split = json.loads((SET / "split.json").read_text(encoding="utf-8"))[part]
    manifest = json.loads((SET / "manifest.json").read_text(encoding="utf-8"))["cases_per_code"]
    photos = json.loads((SET / "photos" / "index.json").read_text(encoding="utf-8"))
    rows: dict[str, list[dict]] = {}
    for line in (SET / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows.setdefault(r["code"], []).append(r)
    tasks = []
    wanted = [c for c in sorted(split, key=lambda c: hashlib.md5(("order|" + c).encode()).hexdigest()) if photos.get(c)]
    langs = photo_languages(wanted)
    for code in wanted:
        name = photos[code]
        newest = max(rows[code], key=lambda r: r["last_modified_t"])
        b64 = base64.b64encode((SET / "photos" / name).read_bytes()).decode()
        tasks.append({"data": {
            "nutrition_photo": f"data:image/jpeg;base64,{b64}",
            "title": f"{newest.get('product_name') or '(no name)'} ({newest.get('brands') or 'no brand'})",
            "barcode": f"Barcode {code}",
            "code": code,
            "group": manifest[code][0],
            "flag_text": flag_text(newest.get("data_quality_errors_tags") or []),
            "fields_to_type": FIELDS_TO_TYPE[manifest[code][0]],
            **cl.glossary_lines({"photo_languages": langs.get(code, [])}),
        }})
    return tasks


NUMBER_FIELDS = {"k_energy_kcal": "energy_kcal", "k_energy_kj": "energy_kj", "k_fat": "fat", "k_saturated_fat": "saturated_fat", "k_carbohydrates": "carbohydrates",
                 "k_sugars": "sugars", "k_fiber": "fiber", "k_proteins": "proteins", "k_salt": "salt", "k_sodium": "sodium"}


def carry_answers(tasks: list[dict], backup_file: Path) -> int:
    """Copy the answers already given in an earlier project (an export of it) into these tasks as finished annotations, one text box per nutrient: numbers from the old number
    boxes, or the values of the one-line form, are written into the matching box ('9.7' in the fat box); the column choice, the serving size and the note are kept as they were.
    Tasks are matched by barcode. Returns how many were carried."""
    import sys
    sys.path.insert(0, str(ROOT / "p8_steward"))
    import answer_key_lib as ak
    box_of = {v: k for k, v in NUMBER_FIELDS.items()}
    backup = {t["data"]["code"]: t for t in json.loads(backup_file.read_text(encoding="utf-8")) if t.get("annotations")}
    carried = 0
    for task in tasks:
        old = backup.get(task["data"]["code"])
        if not old:
            continue
        results, numbers = [], {}
        for r in old["annotations"][0]["result"]:
            if r["type"] == "number" and r["from_name"] in NUMBER_FIELDS:
                numbers[NUMBER_FIELDS[r["from_name"]]] = r["value"]["number"]
            elif r["from_name"] == "values":
                numbers.update(ak.parse(r["value"]["text"][0])["values"])
            elif r["from_name"] in box_of.values():
                numbers.update(ak.parse_boxes({r["from_name"]: r["value"]["text"][0]})["values"])
            else:
                results.append({"from_name": r["from_name"], "to_name": r["to_name"], "type": r["type"], "value": r["value"]})
        for field, number in numbers.items():
            results.append({"from_name": box_of[field], "to_name": "photo", "type": "textarea", "value": {"text": [f"{number:.10g}"]}})
        task["annotations"] = [{"result": results}]
        carried += 1
    return carried


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["dev", "dev2", "test"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--carry-from", help="an export (JSON) of an earlier answer-key project: its finished cards are copied over as answers in the one-line form")
    args = ap.parse_args()
    tasks = build(args.part)
    carried = carry_answers(tasks, Path(args.carry_from)) if args.carry_from else 0
    Path(args.out).write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    print(f"{len(tasks)} tasks for the {args.part} part, {carried} with an answer carried over -> {args.out} ({Path(args.out).stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
