"""Fetches the nutrition photo of every round-2 product (output/review_set/fix_test_round2.json) and resizes it for the photo reader (long side 1,600 px).

  python p8_steward/bootstrap/fetch_round2_photos.py [--set round2|final] [--limit N]        needs Pillow: run it with an interpreter that has it (the project .venv does not)
Steps per product, each resumable: (1) the photo address from OFF's public product API (selected_images.nutrition.display, rewritten to .full.jpg), kept in
output/review_set/photos_round2/addresses.json ('' = OFF has no nutrition photo); (2) the full photo, with the 400 px copy as the fallback, in photos_round2/raw/;
(3) the resized copy photos_round2/<code>.jpg, the file the reader is given. Same pace and user agent as fetch_ocr_text.py. Nothing is sent anywhere from here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_ocr_text as fo  # noqa: E402

SET = fo.SET
OUT = SET / "photos_round2"
LONG_SIDE = 1600


def full_address(display: dict) -> str:
    """The .full.jpg address of the first listed language's display photo; '' when there is none."""
    if not display:
        return ""
    url = sorted(display.items())[0][1]
    return re.sub(r"\.\d+\.jpg$", ".full.jpg", url) if url else ""


def target_size(w: int, h: int, long_side: int = LONG_SIDE) -> tuple[int, int]:
    """The size after resizing: the long side becomes long_side pixels, never enlarged."""
    k = long_side / max(w, h)
    return (w, h) if k >= 1 else (round(w * k), round(h * k))


def address(code: str) -> str:
    product = fo.get_json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images").get("product") or {}
    return full_address(((product.get("selected_images") or {}).get("nutrition") or {}).get("display") or {})


def download(url: str, dest: Path) -> bool:
    for u in (url, url.replace(".full.jpg", ".400.jpg")):
        try:
            data = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": fo.AGENT}), timeout=60).read()
            if len(data) > 1000:
                dest.write_bytes(data)
                return True
        except Exception as e:                                           # noqa: BLE001  (a failed address falls through to the next)
            print("  download failed", u.rsplit("/", 1)[-1], str(e)[:60])
    return False


def resize(src: Path, dest: Path) -> tuple[int, int]:
    from PIL import Image                                                # not a project dependency: only this step needs it
    im = Image.open(src).convert("RGB")
    size = target_size(*im.size)
    if size != im.size:
        im = im.resize(size, Image.LANCZOS)
    im.save(dest, quality=85)
    return size


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--set", choices=["round2", "final"], default="round2", help="which product file: fix_test_<set>.json; photos go to photos_<set>/")
    a = ap.parse_args()
    out = SET / f"photos_{a.set}"
    rows = json.loads((SET / f"fix_test_{a.set}.json").read_text(encoding="utf8"))
    (out / "raw").mkdir(parents=True, exist_ok=True)
    book = out / "addresses.json"
    addresses = json.loads(book.read_text(encoding="utf8")) if book.exists() else {}
    n = 0
    for row in rows:
        code = row["code"]
        if code not in addresses:
            addresses[code] = address(code)
            book.write_text(json.dumps(addresses), encoding="utf8")
        if not addresses[code]:
            continue
        raw, small = out / "raw" / f"{code}.jpg", out / f"{code}.jpg"
        if small.exists():
            continue
        if a.limit and n >= a.limit:
            break
        if not raw.exists() and not download(addresses[code], raw):
            print(code, "NO DOWNLOAD")
            continue
        print(code, "resized to", resize(raw, small), flush=True)
        n += 1
        time.sleep(0.6)
    have = len(list(out.glob("*.jpg")))
    print(f"addresses {len(addresses)} of {len(rows)}; without a photo {sum(1 for v in addresses.values() if not v)}; resized photos on disk {have}")


if __name__ == "__main__":
    main()
