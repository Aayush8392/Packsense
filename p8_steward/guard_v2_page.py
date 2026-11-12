"""Guard v2: the judging page for the values it recovered, and the scoring (pre-registered in output/review_set/guard_and_statements_prereg.md, step 2).

  python p8_steward/guard_v2_page.py html   -> guard_v2_items.json, guard_v2_key.json (NOT in the page), guard_v2_photos.json and guard_v2_page.html (Save writes fix_review_guardv2_answers.json)
  python p8_steward/guard_v2_page.py join   -> reads the answers: the share of recovered values right, per rule and per set, against the bar of 90%

One item per product: the photo and ONLY the values v2 recovered (the other values of the line were judged before or are not in question). Question: do these values match the pack?
Order: sha256('guardv2-order:' + code). A line is right when the owner says so; 'wrong' and 'can't tell' are reported (can't tell as wrong is a sensitivity). Bar: at least 90% right.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import final_page as fp  # noqa: E402
import fix_review_page as frp  # noqa: E402
import fix_test_lib as t  # noqa: E402

R = frp.R
RESULTS = R / "guard_v2_results.json"
ANSWERS = R / "fix_review_guardv2_answers.json"
WHICH = "guardv2"
SETS = {"round2": ("fix_test_round2.json", "photos_round2", "round2"), "final_a": ("fix_test_final_a.json", "photos_final", "final_a")}


def order(codes: list[str]) -> list[str]:
    return sorted(codes, key=lambda c: hashlib.sha256(("guardv2-order:" + c).encode()).hexdigest())


def score(answers: dict, key: dict) -> dict:
    def tally(codes):
        right = sum(answers.get(c) == "right" for c in codes)
        wrong = sum(answers.get(c) == "wrong" for c in codes)
        unsure = sum(answers.get(c) == "unsure" for c in codes)
        n = right + wrong
        lo, hi = t.wilson(right, n) if n else (0.0, 0.0)
        return {"lines": len(codes), "answered": right + wrong + unsure, "right": right, "wrong": wrong, "unsure": unsure, "rate": round(right / n, 3) if n else None, "wilson_95": [round(lo, 3), round(hi, 3)]}
    out = {"all": tally(list(key)), "bar": "at least 90% of recovered-value lines right"}
    for s in SETS:
        out[s] = tally([c for c, k in key.items() if k["set"] == s])
    for r in ("first_decimal", "trailing_9"):
        out[r] = tally([c for c, k in key.items() if r in k["rules"]])
    return out


def cmd_html() -> None:
    import fix_test_agent as fa
    import photo_method as pm
    res = json.loads(RESULTS.read_text(encoding="utf8"))
    items_by_code, key, photos = {}, {}, {}
    for name, (rows_file, photo_dir, which) in SETS.items():
        rows = {r["code"]: r for r in json.loads((R / rows_file).read_text(encoding="utf8"))}
        text_r = json.loads(fa.files(which, pm.MODEL)[1].read_text(encoding="utf-8"))
        addresses = json.loads((R / photo_dir / "addresses.json").read_text(encoding="utf8"))
        for code, g in res[name]["lines_gaining_values"].items():
            f = R / "ocr_json" / f"{code}.json"
            scan = json.loads(f.read_text(encoding="utf8")) if f.exists() and f.stat().st_size > 2 else None
            items_by_code[code] = fp.build_item(rows[code], frp.candidate_values(g["added"]), (text_r.get(code) or {}).get("reading"), scan)
            key[code] = {"set": name, "fields": g["added"], "rules": sorted({e["rule"] for e in g["evidence"]}), "tokens": [e["token"] for e in g["evidence"]]}
            photos[code] = addresses.get(code, "")
    codes = order(list(items_by_code))
    items = [items_by_code[c] for c in codes]
    (R / "guard_v2_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf8")
    (R / "guard_v2_key.json").write_text(json.dumps(key, indent=0), encoding="utf8")
    (R / "guard_v2_photos.json").write_text(json.dumps(photos), encoding="utf8")
    out = R / "guard_v2_page.html"
    out.write_text(fp.render(items, photos, WHICH), encoding="utf8")
    print("written", out, "| lines", len(items), "| values", sum(len(k["fields"]) for k in key.values()), "| without a photo address:", sum(not v for v in photos.values()))


def cmd_join() -> None:
    key = json.loads((R / "guard_v2_key.json").read_text(encoding="utf8"))
    print(json.dumps(score(json.loads(ANSWERS.read_text(encoding="utf8")), key), indent=1))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"html": cmd_html, "join": cmd_join}.get(cmd, lambda: sys.exit(__doc__))()


if __name__ == "__main__":
    main()
