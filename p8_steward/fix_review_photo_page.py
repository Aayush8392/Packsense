"""Blind review page for the PHOTO READING (Phase 1 follow-up): does the table the photo reader produced match the pack? Same page, same keys and answers as the round-1 review (A, B, both, neither,
can't tell); private, local, nothing published.

  python p8_steward/fix_review_photo_page.py items   -> output/review_set/fix_review_photo1_{items,key}.json
  python p8_steward/fix_review_photo_page.py html    -> output/review_set/fix_review_photo1.html  (answers are saved as fix_review_photo1_answers.json)
  python p8_steward/fix_review_photo_page.py join    -> who was right, from the answers and the key

Table A or B is the photo reading (values the OCR text does not print are dropped, as in the method), the other is a COMPARISON table, order randomised by the parity of sha256('swap-2:' + code).
Cases (fixed before any answer):
  neither   every round-1 case where the owner found neither table right (17): comparison = the hybrid's table (known wrong). The photo reading is the only candidate for the truth there.
  mismatch  every case with a known-right table where the photo reading is usable but does NOT agree with it (the 90%-of-fields rule): comparison = the table the owner found right.
  control   8 cases where the photo reading DOES agree with the known-right table and the other candidate was wrong (first 8 by sha256('control-1:' + code)): comparison = that wrong table.
            They are there so that the page does not tell the owner which tables to doubt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_review_page as frp  # noqa: E402
import ocr_variant_test as ov  # noqa: E402
import vision_variant_test as vv  # noqa: E402

R = ov.R
WHICH = "photo1"
CONTROLS = 8


def h(prefix: str, code: str) -> str:
    return hashlib.sha256((prefix + code).encode()).hexdigest()


def photo_first(code: str) -> bool:
    """True when the photo reading is table A (decided by a hash, so the position tells nothing)."""
    return int(h("swap-2:", code), 16) % 2 == 0


def select(cases: list[dict], photo: dict, comparison: dict) -> list[dict]:
    """cases = judged cases (code, who, truth); photo = code -> photo reading (per 100) or None; comparison = code -> {'right': table|None, 'wrong': table|None, 'hybrid': table}.
    Returns [{'code', 'kind', 'other'}] in page order (shuffled by sha256('order-2:' + code))."""
    out = []
    controls = []
    for c in cases:
        code, p = c["code"], photo.get(c["code"])
        if not p:
            continue
        if c["truth"] is None:
            out.append({"code": code, "kind": "neither", "other": comparison[code]["hybrid"]})
        elif not ov.agree(p, c["truth"]):
            out.append({"code": code, "kind": "mismatch", "other": c["truth"]})
        elif comparison[code]["wrong"] is not None:
            controls.append({"code": code, "kind": "control", "other": comparison[code]["wrong"]})
    controls.sort(key=lambda r: h("control-1:", r["code"]))
    out += controls[:CONTROLS]
    return sorted(out, key=lambda r: h("order-2:", r["code"]))


def build(row: dict, entry: dict, photo_table: dict, other: dict, before: dict, scan: dict | None, vision_reading: dict | None) -> tuple[dict, dict]:
    p, o = frp.candidate_values(photo_table), frp.candidate_values(other)
    first = photo_first(row["code"])
    a, b = (p, o) if first else (o, p)
    size, src = frp.serving_for_page(row, vision_reading)
    item = {"code": row["code"], "A": a, "B": b, "stored_before": before, "serving": row.get("serving_size") or "", "serving_g": size, "serving_src": src,
            "basis_hint": (vision_reading or {}).get("basis") or "", "glossary": frp.glossary_from_scan(scan)}
    key = {"A": "photo" if first else "other", "B": "other" if first else "photo", "kind": entry["kind"]}
    return item, key


def cmd_items() -> None:
    cases = ov.judged_cases()
    items_r1 = {i["code"]: i for i in json.loads((R / "fix_review_round1_items.json").read_text(encoding="utf8"))}
    key_r1 = json.loads((R / "fix_review_round1_key.json").read_text(encoding="utf8"))
    rows = {r["code"]: r for r in json.loads((R / "fix_test_round1.json").read_text(encoding="utf8"))}
    v0 = {c["code"]: ov.text_for("v0", c["code"]) for c in cases}
    vr = json.loads((ov.OUT / "readings_vision.json").read_text(encoding="utf-8"))
    photo = {c["code"]: vv.vision_per100(vr.get(c["code"]) or {}, v0[c["code"]]) for c in cases}
    comparison = {}
    for c in cases:
        it, k = items_r1[c["code"]], key_r1[c["code"]]
        side = lambda src: it["A"] if k["A"] == src else it["B"]      # noqa: E731
        right = c["truth"]
        # the table the owner found WRONG, when exactly one was: used as the comparison of a control
        wrong = side("contributor") if c["who"] == "hybrid" else side("hybrid") if c["who"] == "contributor" else None
        comparison[c["code"]] = {"right": right, "wrong": wrong, "hybrid": side("hybrid")}
    chosen = select(cases, photo, comparison)
    items, key = [], {}
    for e in chosen:
        code = e["code"]
        scan = ov.scan_json(code) or None
        item, k = build(rows[code], e, photo[code], e["other"], items_r1[code]["stored_before"], scan, (vr.get(code) or {}).get("reading"))
        items.append(item)
        key[code] = k
    (R / f"fix_review_{WHICH}_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf8")
    (R / f"fix_review_{WHICH}_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=0), encoding="utf8")
    kinds = [k["kind"] for k in key.values()]
    print(len(items), "items:", {k: kinds.count(k) for k in ("neither", "mismatch", "control")})


def cmd_html() -> None:
    items = json.loads((R / f"fix_review_{WHICH}_items.json").read_text(encoding="utf8"))
    photos = json.loads((R / "fix_review_round1_photos.json").read_text(encoding="utf8"))
    shown = [i for i in items if photos.get(i["code"])]
    out = R / f"fix_review_{WHICH}.html"
    out.write_text(frp.render(shown, photos, WHICH), encoding="utf8")
    print("written", out, "| shown", len(shown), "of", len(items))


def join(answers: dict, key: dict) -> dict:
    """Per kind: how often the PHOTO table was right (chosen, or 'both'), wrong, or the owner could not tell."""
    out: dict = {}
    for code, a in answers.items():
        k = key[code]
        who = {"A": k["A"], "B": k["B"]}.get(a, a)
        bucket = "photo_right" if who in ("photo", "both") else "photo_wrong" if who in ("other", "neither") else "unsure"
        out.setdefault(k["kind"], {}).setdefault(bucket, 0)
        out[k["kind"]][bucket] += 1
    return out


def cmd_join() -> None:
    key = json.loads((R / f"fix_review_{WHICH}_key.json").read_text(encoding="utf8"))
    answers = json.loads((R / f"fix_review_{WHICH}_answers.json").read_text(encoding="utf8"))
    print(json.dumps(join(answers, key), indent=1), "| answered", len(answers), "of", len(key))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["items", "html", "join"])
    {"items": cmd_items, "html": cmd_html, "join": cmd_join}[ap.parse_args().cmd]()


if __name__ == "__main__":
    main()
