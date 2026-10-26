"""Pick the cards for the labelling gate and write the Label Studio task files (Phase D item 16). Admin, read-only on production; the output stays OUTSIDE the repo.

  .venv\\Scripts\\python.exe p7_triage_ml\\labelling\\select_cards.py --env-file .env --out D:\\off-catalogue-platform\\label_studio\\packsense_gate

Steps: (1) the products with an open nutrition-number flag in the labelling scope that none of our 11 rules marks as violated and that OFF has not removed; (2) order them by the md5 of the
barcode (no randomness, nobody chooses); (3) walk the order, ask OFF's product API (3 s apart, answers cached) and keep a product when it has a selected nutrition photo and its flag
family has room under the cap; (4) the first 20 become two practice sets of 10 (cap 4 per family), the next 30 the real test set (cap 6 per family). The real set is written to a file
and NOT printed. Prints counts only.
"""
from __future__ import annotations

import argparse
import hashlib
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "p4_modelling" / "bootstrap"))
sys.path.insert(0, str(ROOT / "p9_operations"))
import cards_lib as cl  # noqa: E402
import fixture_databricks as fd  # noqa: E402
import snapshot_lib as sl  # noqa: E402

SCHEMA = "workspace.packsense_gold"
FIRST = 700                  # candidates read from production in hash order (enough for the photo filter; a rerun with a larger number extends the walk)
AGENT = "PackSense-labelling/0.1 (research project; contact via the GitHub repository Aayush8392/Packsense)"
PRACTICE_CAP, REAL_CAP, THIRD_CAP = 4, 6, 2


def candidates(w) -> list[dict]:
    rows = fd.run_sql(w, f"""
        select s.code, s.flag from {SCHEMA}.product_flag_spans s
        where s.is_open = 1 and s.severity in ('error', 'warning')
          and (s.flag like '%value-very-%' or s.flag like '%value-under-0-0%' or s.flag like '%{cl.IDENTICAL}%')""").result.data_array
    families: dict[str, set[str]] = {}
    for code, flag in rows:
        fam = sl.family_key(flag)
        if cl.in_scope(fam):
            families.setdefault(code, set()).add(fam)
    violated = {r[0] for r in fd.run_sql(w, f"select distinct code from {SCHEMA}.product_rule_verdicts where status = 'violated'").result.data_array}
    removed = {r[0] for r in fd.run_sql(w, f"select code from {SCHEMA}.mart_product_card where existence_status in ('confirmed_not_found', 'moved_other_type')").result.data_array}
    ok = [c for c in families if c not in violated and c not in removed]
    ok.sort(key=lambda c: hashlib.md5(c.encode()).hexdigest())
    print(f"products with an in-scope open flag {len(families)}; a rule violated {len(set(families) & violated)}; removed or moved {len(set(families) & removed)}; eligible {len(ok)}")
    head = ok[:FIRST]
    quoted = ", ".join(f"'{c}'" for c in head)
    cols = "code, product_name, brands, quantity_amount, quantity_unit, serving_amount, serving_unit, nutrition_per, nutrition_preparation, " + ", ".join(k for k, _, _ in cl.VALUE_ROWS)
    data = fd.run_sql(w, f"select {cols} from {SCHEMA}.product_history where is_latest_observed = 1 and code in ({quoted})").result.data_array
    names = [c.strip() for c in cols.split(",")]
    by_code = {}
    for r in data:
        d = dict(zip(names, r))
        for k in ("quantity_amount", "serving_amount") + tuple(k for k, _, _ in cl.VALUE_ROWS):
            d[k] = None if d[k] is None else float(d[k])
        by_code[d["code"]] = d
    usable = [c for c in head if c in by_code and cl.usable_record(by_code[c])]
    print(f"of the first {len(head)}: no per-100 basis or a rule violated on the shown numbers {len([c for c in head if c in by_code]) - len(usable)}; usable {len(usable)}")
    return [{"row": by_code[c], "families": sorted(families[c])} for c in usable]


class Off:
    """OFF's product API (3 s apart) for the photo addresses, and the text scan OFF keeps next to each photo for its detected languages (a different host; 1 s apart). Answers are cached."""

    def __init__(self, cache_file: Path):
        self.file, self.cache = cache_file, (json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {})
        self.calls = 0
        self.seen = self.passed = 0

    def photos(self, code: str) -> dict | None:
        if code not in self.cache:
            self.cache[code] = self._entry(code)
            self.file.write_text(json.dumps(self.cache), encoding="utf-8")
        entry = self.cache[code]
        photos = cl.photo_urls(entry["product"]) if entry["product"] else None
        if not photos:
            return None
        self.seen += 1
        if entry["ocr"] is None or not cl.readable(entry["ocr"]):
            return None                                           # no text scan, or no language the word lists cover
        self.passed += 1
        return {**photos, "ocr": entry["ocr"]}

    def _entry(self, code: str) -> dict:
        product = self._json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images,images", 3).get("product") or {}
        photos = cl.photo_urls(product) if product else None
        ocr = None
        if photos:
            m = re.search(r"/products/(.+)/nutrition_([a-z]+)\.\d+\.", photos["nutrition_full"])
            imgid = ((product.get("images") or {}).get(f"nutrition_{m.group(2)}") or {}).get("imgid") if m else None
            if imgid:
                scan = self._json(f"https://images.openfoodfacts.org/images/products/{m.group(1)}/{imgid}.json", 1)
                ocr = [[c, round(p, 3)] for c, p in cl.ocr_languages(scan)] if scan else None
        return {"product": {"selected_images": product.get("selected_images")} if product else {}, "ocr": ocr}

    def _json(self, url: str, pace: int) -> dict:
        for attempt in range(4):
            time.sleep(pace)
            self.calls += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
                    raw = r.read()
                if raw[:2] == b"\x1f\x8b":                                  # some scan files are stored gzipped and served as they are
                    raw = gzip.decompress(raw)
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    return {}
                time.sleep(30 * (attempt + 1))                     # 429 and the like: back off
            except ValueError:
                return {}                                              # not JSON (or not text): treated as 'no scan', the card is not kept
            except (urllib.error.URLError, TimeoutError):
                time.sleep(10)
        raise SystemExit(f"OFF did not answer for {url}; rerun later (answers so far are cached)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fd.load_env_file(args.env_file)
    cands = candidates(fd.client())
    off = Off(out / "off_cache2.json")
    taken: set[str] = set()
    practice = cl.select(cands, off.photos, 20, PRACTICE_CAP, taken)
    real = cl.select(cands, off.photos, 30, REAL_CAP, taken)
    extra = [cl.select(cands, off.photos, 10, THIRD_CAP, taken) for _ in range(3)]      # practice sets 3 to 5, chosen AFTER the real set so the real set cannot change
    if len(practice) < 20 or len(real) < 30 or any(len(s) < 10 for s in extra):
        raise SystemExit(f"not enough cards (practice {len(practice)}, real {len(real)}): raise FIRST and rerun")
    sets = {"practice_1": practice[:10], "practice_2": practice[10:], "real_test": real, "practice_3": extra[0], "practice_4": extra[1], "practice_5": extra[2]}
    for name, cards in sets.items():
        tasks = [cl.make_task(c["row"], c["families"], c["photos"], name, i) for i, c in enumerate(cards, start=1)]
        path = out / (f"{name}.json" if name != "real_test" else "real_test.SEALED.json")
        path.write_text(json.dumps(tasks, indent=1, ensure_ascii=False), encoding="utf-8")
    manifest = {name: [c["row"]["code"] for c in cards] for name, cards in sets.items()}
    (out / "selection_manifest.SEALED.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"OFF calls this run: {off.calls}; photos with a nutrition photo examined {off.seen}, with a listed language {off.passed} ({off.passed / max(off.seen, 1):.0%})")
    for name, cards in sets.items():
        fams: dict[str, int] = {}
        for c in cards:
            fams[c["families"][0]] = fams.get(c["families"][0], 0) + 1
        print(f"{name}: {len(cards)} cards; families {len(fams)}; largest family {max(fams.values())}")
    assert not (set(manifest["real_test"]) & (set(manifest["practice_1"]) | set(manifest["practice_2"]) | set(manifest["practice_3"]) | set(manifest["practice_4"]) | set(manifest["practice_5"]))), "practice and real sets overlap"


if __name__ == "__main__":
    main()
