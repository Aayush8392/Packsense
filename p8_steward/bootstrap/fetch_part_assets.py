"""Downloads, for one part of the review set, what the answer key and the reader need from Open Food Facts: the nutrition photo, OFF's text scan (OCR) of it, and the languages
the scan found. Into output/review_set/ (gitignored, private working copy): photos/<code>.jpg and photos/index.json, ocr_text/<code>.txt, ocr_languages.json.

  python p8_steward/bootstrap/fetch_part_assets.py --part dev2
Three requests per product (the product record, the photo, the scan), 4 seconds apart; a refused connection is retried once after 15 seconds, then the run stops and keeps what it has
(a rerun resumes). A product with no selected nutrition photo is recorded as such and is left out of the labelling.
"""
from __future__ import annotations

import argparse
import gzip
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
import cards_lib as cl  # noqa: E402

AGENT = "packsense-review-set/1 (private research use)"
PACE = 4.0


def get(url: str) -> bytes:
    for attempt in range(2):
        time.sleep(PACE if attempt == 0 else 15)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
                raw = r.read()
            return gzip.decompress(raw) if raw[:2] == bytes([0x1F, 0x8B]) else raw
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return b""
            raise SystemExit(f"Open Food Facts answered HTTP {e.code} for {url.split('?')[0]}; stopped, done so far is kept")
        except (urllib.error.URLError, TimeoutError):
            continue
    raise SystemExit(f"Open Food Facts did not answer for {url.split('?')[0]}; run again later (done so far is kept)")


def as_json(raw: bytes) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    args = ap.parse_args()
    codes = json.loads((SET / "split.json").read_text(encoding="utf-8"))[args.part]
    (SET / "photos").mkdir(exist_ok=True)
    (SET / "ocr_text").mkdir(exist_ok=True)
    index_file, lang_file = SET / "photos" / "index.json", SET / "ocr_languages.json"
    index = json.loads(index_file.read_text(encoding="utf-8"))
    langs = json.loads(lang_file.read_text(encoding="utf-8")) if lang_file.exists() else {}
    n_new = n_photo = 0
    for code in codes:
        if code in index:
            continue
        product = as_json(get(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images,images")).get("product") or {}
        photos = cl.photo_urls(product) if product else None
        n_new += 1
        if not photos:
            index[code] = None
        else:
            body = get(photos["nutrition_full"]) or get(photos["nutrition_400"])
            if body:
                (SET / "photos" / f"{code}.jpg").write_bytes(body)
                index[code] = f"{code}.jpg"
                n_photo += 1
            else:
                index[code] = None
            m = re.search(r"/products/(.+)/nutrition_([a-z]+)\.\d+\.", photos["nutrition_full"])
            imgid = ((product.get("images") or {}).get(f"nutrition_{m.group(2)}") or {}).get("imgid") if m else None
            scan = as_json(get(f"https://images.openfoodfacts.org/images/products/{m.group(1)}/{imgid}.json")) if imgid else {}
            texts = [(r.get("fullTextAnnotation") or {}).get("text", "") for r in (scan.get("responses") or [])]
            (SET / "ocr_text" / f"{code}.txt").write_text("\n".join(t for t in texts if t), encoding="utf-8")
            langs[code] = cl.printed_languages(cl.ocr_languages(scan)) if scan else []
        index_file.write_text(json.dumps(index), encoding="utf-8")
        lang_file.write_text(json.dumps(langs), encoding="utf-8")
        print(code, "photo" if index[code] else "no photo", flush=True)
    print(f"{n_new} products looked up, {n_photo} photos downloaded; {sum(1 for c in codes if index.get(c))} of {len(codes)} products in {args.part} have a photo")


if __name__ == "__main__":
    main()
