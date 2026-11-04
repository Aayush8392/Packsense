"""Fetches OFF's own raw scan file (Google Vision output, with word positions) of each nutrition photo, into output/review_set/ocr_json/ (gitignored, private working copy).

  python p8_steward/bootstrap/fetch_ocr_json.py --part dev|dev2 [--only-usable] [--limit N]
Same source and pace as fetch_ocr_text.py (two small requests per product, 4 seconds apart); it keeps the whole scan file, not just the text, so the table can be rebuilt from word positions.
A product with no scan gets an empty marker file so a rerun does not ask again.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_ocr_text as fo  # noqa: E402

SET = fo.SET
OUT = SET / "ocr_json"


def scan_json(code: str) -> dict:
    product = fo.get_json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images,images").get("product") or {}
    nut = ((product.get("selected_images") or {}).get("nutrition") or {}).get("display") or {}
    if not nut:
        return {}
    lang, url = sorted(nut.items())[0]
    m = re.search(r"/products/(.+)/nutrition_([a-z]+)\.\d+\.", url)
    imgid = ((product.get("images") or {}).get(f"nutrition_{m.group(2)}") or {}).get("imgid") if m else None
    if not imgid:
        return {}
    return fo.get_json(f"https://images.openfoodfacts.org/images/products/{m.group(1)}/{imgid}.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["dev", "dev2"], required=True)
    ap.add_argument("--only-usable", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--codes", nargs="*")
    a = ap.parse_args()
    key = json.loads((SET / f"answer_key_{a.part}_key.json").read_text(encoding="utf-8"))["cards"]
    codes = a.codes or [c for c, e in key.items() if (e["usable"] or not a.only_usable)]
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for code in codes:
        f = OUT / f"{code}.json"
        if f.exists():
            continue
        f.write_text(json.dumps(scan_json(code), ensure_ascii=False), encoding="utf-8")
        n += 1
        print(code, f.stat().st_size, "bytes", flush=True)
        if a.limit and n >= a.limit:
            break
    print(f"fetched {n}; {len(list(OUT.glob('*.json')))} files in {OUT}")


if __name__ == "__main__":
    main()
