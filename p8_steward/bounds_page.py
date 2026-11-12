"""The bound statements (repair_record.bound_statements) on round 2 and batch A, and the page to judge them (pre-registered in output/review_set/guard_and_statements_prereg.md, step 4).

  python p8_steward/bounds_page.py html   -> bounds_items.json, bounds_key.json (NOT in the page), bounds_photos.json and bounds_page.html (Save writes fix_review_bounds_answers.json)
  python p8_steward/bounds_page.py join   -> reads the answers: how many bounds are right

One item per product with a bound: the photo, the confirmed line (the photo table with the values guard v2 recovered) and the statement. Question: is the statement true, that is, is the stored value
really wrong or out of date given what the pack prints? A bound is right when the owner says yes. Decoy lines of the final block are judged on their REAL line here (the altered kcal of the judging page
is not used).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_review_page as frp  # noqa: E402
import fix_test_lib as t  # noqa: E402
import final_page as fp  # noqa: E402
import fix_candidates as fc  # noqa: E402
import repair_record as rr  # noqa: E402

R = frp.R
ANSWERS = R / "fix_review_bounds_answers.json"
WHICH = "bounds"
SETS = {"round2": ("fix_test_round2.json", "photos_round2", "round2"), "final_a": ("fix_test_final_a.json", "photos_final", "final_a")}
CHOICES = ('const CH=[["right","1","Yes: the stored value is wrong or out of date"],["wrong","2","No: the statement is not true (the stored value is fine)"],'
           '["unsure","3","I can\'t tell"]];')
INTRO = ("Look at the photo. Our line below shows the values we confirmed. Read the statement under it: is it TRUE, that is, given what the pack prints, is the stored value really wrong or out of date? "
         "Only printed values decide.")


def bound_cases() -> list[dict]:
    import fix_test_agent as fa
    import photo_method as pm
    results = json.loads((R / "guard_v2_results.json").read_text(encoding="utf8"))
    cases = []
    for name, (rows_file, photo_dir, which) in SETS.items():
        rows = json.loads((R / rows_file).read_text(encoding="utf8"))
        text_r = json.loads(fa.files(which, pm.MODEL)[1].read_text(encoding="utf-8"))
        photo_r = json.loads((R / f"fix_test_photo_readings_{which}__{pm.MODEL}.json").read_text(encoding="utf-8"))
        addresses = json.loads((R / photo_dir / "addresses.json").read_text(encoding="utf8"))
        for row in rows:
            c = row["code"]
            text = pm.ocr_text(c) if (R / "ocr_json" / f"{c}.json").exists() else ""
            d = pm.decide(c, text_r.get(c), photo_r.get(c), text, t.before(row), has_photo=(R / photo_dir / f"{c}.jpg").exists())
            if not (d["rule2"] and d["table"] is not None):
                continue
            b = t.before(row)
            tab = {f: v for f, v in d["table"].items() if v is not None}
            tab = {**tab, **results[name]["lines_gaining_values"].get(c, {}).get("added", {})}
            rec, _ = rr.repaired_record(b, tab)
            vr = fc.violations(rec)
            if not fc.violations(b) or not vr:
                continue
            bs = rr.bound_statements(b, tab, set(vr))
            if bs:
                cases.append({"set": name, "code": c, "row": row, "table": tab, "statements": bs, "photo": addresses.get(c, ""), "reading": (text_r.get(c) or {}).get("reading")})
    return cases


def score(answers: dict, key: dict) -> dict:
    def tally(codes):
        right = sum(answers.get(c) == "right" for c in codes)
        wrong = sum(answers.get(c) == "wrong" for c in codes)
        unsure = sum(answers.get(c) == "unsure" for c in codes)
        return {"bounds": len(codes), "answered": right + wrong + unsure, "right": right, "wrong": wrong, "unsure": unsure}
    out = {"all": tally(list(key))}
    for s in SETS:
        out[s] = tally([c for c, k in key.items() if k["set"] == s])
    return out


def cmd_html() -> None:
    cases = bound_cases()
    items, key, photos = [], {}, {}
    for cs in sorted(cases, key=lambda x: x["code"]):
        f = R / "ocr_json" / f"{cs['code']}.json"
        scan = json.loads(f.read_text(encoding="utf8")) if f.exists() and f.stat().st_size > 2 else None
        item = fp.build_item(cs["row"], frp.candidate_values(cs["table"]), cs["reading"], scan)
        item["statement"] = " ".join(s["text"] for s in cs["statements"])
        if "per serving" in str((cs["reading"] or {}).get("basis") or "") and "per 100" not in str((cs["reading"] or {}).get("basis") or ""):
            item["statement"] += f" (The pack prints per-serving values only, per {(cs['reading'] or {}).get('serving_size') or 'the serving'}: the per-100 figures above are converted from the serving, so compare them with the serving values on the pack.)"
        items.append(item)
        key[cs["code"]] = {"set": cs["set"], "statements": cs["statements"]}
        photos[cs["code"]] = cs["photo"]
    (R / "bounds_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf8")
    (R / "bounds_key.json").write_text(json.dumps(key, indent=0), encoding="utf8")
    (R / "bounds_photos.json").write_text(json.dumps(photos), encoding="utf8")
    out = R / "bounds_page.html"
    out.write_text(fp.render(items, photos, WHICH, choices=CHOICES, intro=INTRO), encoding="utf8")
    print("written", out, "| bounds", len(items), "| without a photo address:", sum(not v for v in photos.values()))
    for it in items:
        print("  ", it["code"], key[it["code"]]["set"], "|", it["statement"])


def cmd_join() -> None:
    key = json.loads((R / "bounds_key.json").read_text(encoding="utf8"))
    print(json.dumps(score(json.loads(ANSWERS.read_text(encoding="utf8")), key), indent=1))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"html": cmd_html, "join": cmd_join}.get(cmd, lambda: sys.exit(__doc__))()


if __name__ == "__main__":
    main()
