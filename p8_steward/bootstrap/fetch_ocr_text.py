"""Fetches OFF's own text scan (OCR) of each nutrition photo for the review-set cards, as plain text, into output/review_set/ocr_text/ (gitignored, private working copy).

  python p8_steward/bootstrap/fetch_ocr_text.py --part dev [--only-usable]
One small API reply and one scan file per product, 4 seconds between requests (Open Food Facts refused connections at 1.5 s). A product with no scan gets an empty file, so a rerun
does not ask again. The scan is OFF's own record of the photo (Google Vision output); nothing is sent anywhere from here.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "output" / "review_set"
OUT = SET / "ocr_text"
AGENT = "packsense-review-set/1 (private research use)"
PACE = 4.0


def get_json(url: str) -> dict:
    for attempt in range(2):
        time.sleep(PACE if attempt == 0 else 15)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
                raw = r.read()
            if raw[:2] == bytes([0x1F, 0x8B]):
                raw = gzip.decompress(raw)
            return json.loads(raw)
        except (urllib.error.HTTPError, ValueError):
            return {}
        except (urllib.error.URLError, TimeoutError):
            continue
    raise SystemExit(f"Open Food Facts did not answer for {url.split('?')[0]}; run again later (done so far is kept)")


def scan_text(code: str) -> str:
    product = get_json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images,images").get("product") or {}
    nut = ((product.get("selected_images") or {}).get("nutrition") or {}).get("display") or {}
    if not nut:
        return ""
    lang, url = sorted(nut.items())[0]
    m = re.search(r"/products/(.+)/nutrition_([a-z]+)\.\d+\.", url)
    imgid = ((product.get("images") or {}).get(f"nutrition_{m.group(2)}") or {}).get("imgid") if m else None
    if not imgid:
        return ""
    scan = get_json(f"https://images.openfoodfacts.org/images/products/{m.group(1)}/{imgid}.json")
    texts = [(r.get("fullTextAnnotation") or {}).get("text", "") for r in (scan.get("responses") or [])]
    return "\n".join(t for t in texts if t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["dev", "test"], required=True)
    ap.add_argument("--only-usable", action="store_true", help="only cards the answer key can use (needs answer_key_<part>_key.json)")
    args = ap.parse_args()
    codes = json.loads((SET / "split.json").read_text(encoding="utf-8"))[args.part]
    photos = json.loads((SET / "photos" / "index.json").read_text(encoding="utf-8"))
    codes = [c for c in codes if photos.get(c)]
    if args.only_usable:
        key = json.loads((SET / f"answer_key_{args.part}_key.json").read_text(encoding="utf-8"))["cards"]
        codes = [c for c in codes if key.get(c, {}).get("usable")]
    OUT.mkdir(parents=True, exist_ok=True)
    done = empty = 0
    for code in codes:
        f = OUT / f"{code}.txt"
        if f.exists():
            continue
        f.write_text(scan_text(code), encoding="utf-8")
        done += 1
        empty += f.stat().st_size == 0
        print(code, f.stat().st_size, "chars", flush=True)
    print(f"fetched {done} scans ({empty} empty); {len(list(OUT.glob('*.txt')))} files in {OUT}")


if __name__ == "__main__":
    main()
