"""Stage 2 of the nightly job's soak test: the owner judges about 30 of the lines the first real night wrote (pre-written 2026-11-13, session 49, before any line was seen).

  1. download by hand from the private dataset: lines/current.json (and, for the record, runs/<night>.json)  -> any folder (no token on the laptop)
  python p8_steward/nightly/stage2_judge.py draw   --lines <lines/current.json> --night YYYY-MM-DD     -> output/review_set/stage2_draw.json (never overwritten)
  python p8_steward/nightly/stage2_judge.py photos                                                      -> OFF photo addresses, 4 s apart (the page loads photos from OFF)
  python p8_steward/nightly/stage2_judge.py html   [--extend]                                           -> output/review_set/stage2_page.html (Save writes fix_review_stage2_answers.json)
  python p8_steward/nightly/stage2_judge.py join                                                        -> the answers against the pass rule

The page is the final block's page (final_page.render): one line at a time, the pack photo and OUR line (the photo table) only, right / wrong / can't tell. Nothing here is published.
Draw: sample = first 30 lines of the night in sha256('stage2-judge:' + code) order; extension = the next 10 (shown only with --extend); decoys = the first 5 later lines that carry kcal in
sha256('stage2-decoy:' + code) order, each shown with kcal x 1.5 (rounded), so the right answer is 'wrong'; page order = sha256('stage2-order:' + code).
PASS RULE (fixed before any result): decoys caught as wrong at least 4 of 5, else the judging is VOID (redo on a new draw); at least 25 sample lines judged right or wrong (can't tell is
excluded and reported), else EXTEND (--extend adds 10); then PASS when right >= 90% of those judged (27 of 30), else FAIL. The Wilson interval is information only: 30 lines is a smoke
test, the public claim rests on the final block.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))

R = ROOT / "output" / "review_set"
WHICH = "stage2"
SAMPLE_N, EXTRA_N, DECOY_N = 30, 10, 5
DECOY_FACTOR = 1.5
MIN_JUDGED, PASS_SHARE, MIN_DECOYS_CAUGHT = 25, 0.90, 4
DRAW = R / "stage2_draw.json"
ANSWERS = R / f"fix_review_{WHICH}_answers.json"
EMPTY_GLOSSARY = {"title": "", "note": "", "lines": []}


def h(prefix: str, code: str) -> str:
    return hashlib.sha256((prefix + code).encode()).hexdigest()


def draw(lines: dict[str, dict], night: str) -> dict:
    """Pure and repeatable. lines = code -> the line (values dict). Only lines written on `night` count. Returns {'sample', 'extension', 'decoys', 'order'}."""
    ok = {c: ln for c, ln in lines.items() if isinstance(ln, dict) and ln.get("night") == night and isinstance(ln.get("values"), dict) and ln["values"]}
    by_judge = sorted(ok, key=lambda c: h("stage2-judge:", c))
    sample, extension, rest = by_judge[:SAMPLE_N], by_judge[SAMPLE_N:SAMPLE_N + EXTRA_N], by_judge[SAMPLE_N + EXTRA_N:]
    pool = sorted((c for c in rest if ok[c]["values"].get("energy_kcal") is not None), key=lambda c: h("stage2-decoy:", c))
    decoys = {c: {"original_kcal": ok[c]["values"]["energy_kcal"], "shown_kcal": round(ok[c]["values"]["energy_kcal"] * DECOY_FACTOR)} for c in pool[:DECOY_N]}
    return {"night": night, "lines_on_night": len(ok), "sample": sample, "extension": extension, "decoys": decoys,
            "values": {c: ok[c]["values"] for c in sample + extension + list(decoys)}}


def page_codes(d: dict, extend: bool) -> list[str]:
    codes = list(d["sample"]) + (list(d["extension"]) if extend else []) + list(d["decoys"])
    return sorted(codes, key=lambda c: h("stage2-order:", c))


def item(code: str, values: dict, decoys: dict) -> dict:
    """One page item: only the photo table of the line (a decoy has its kcal replaced). No stored values, no model, no line type are in it."""
    v = {f: round(float(x), 3) for f, x in values.items() if x is not None}
    if code in decoys:
        v["energy_kcal"] = decoys[code]["shown_kcal"]
    return {"code": code, "A": v, "B": {}, "stored_before": {}, "serving": "", "serving_g": None, "serving_src": "", "basis_hint": "", "glossary": EMPTY_GLOSSARY}


def score(answers: dict, key: dict) -> dict:
    """answers: code -> right / wrong / unsure. key: code -> 'sample' or 'decoy'. Applies the pass rule written above."""
    sample = [c for c, k in key.items() if k == "sample"]
    decoys = [c for c, k in key.items() if k == "decoy"]
    right = sum(answers.get(c) == "right" for c in sample)
    wrong = sum(answers.get(c) == "wrong" for c in sample)
    unsure = sum(answers.get(c) == "unsure" for c in sample)
    unanswered = sum(c not in answers for c in sample)
    caught = sum(answers.get(c) == "wrong" for c in decoys)
    judged = right + wrong
    import fix_test_lib as t
    lo, hi = t.wilson(right, judged) if judged else (0.0, 0.0)
    if unanswered or any(c not in answers for c in decoys):
        verdict = "incomplete: answer every line first"
    elif caught < MIN_DECOYS_CAUGHT:
        verdict = "VOID: too few decoys caught; redo on a new draw"
    elif judged < MIN_JUDGED:
        verdict = "EXTEND: fewer than 25 lines judged; run html --extend and judge the 10 more"
    else:
        verdict = "PASS" if right >= PASS_SHARE * judged else "FAIL"
    return {"verdict": verdict, "sample_lines": len(sample), "right": right, "wrong": wrong, "unsure": unsure, "unanswered": unanswered,
            "rate": round(right / judged, 3) if judged else None, "wilson_95_information_only": [round(lo, 3), round(hi, 3)],
            "decoys": {"lines": len(decoys), "caught_as_wrong": caught, "missed_as_right": sum(answers.get(c) == "right" for c in decoys),
                       "unsure": sum(answers.get(c) == "unsure" for c in decoys)}}


def cmd_draw(lines_path: str, night: str) -> None:
    if DRAW.exists():
        sys.exit(f"{DRAW.name} exists: the draw is never overwritten (delete it by hand to redo)")
    lines = json.loads(Path(lines_path).read_text(encoding="utf-8"))
    d = draw(lines, night)
    if len(d["sample"]) < SAMPLE_N or len(d["decoys"]) < DECOY_N:
        sys.exit(f"the night {night} holds {d['lines_on_night']} usable lines: {len(d['sample'])} for the sample, {len(d['decoys'])} decoys; not enough")
    R.mkdir(parents=True, exist_ok=True)
    DRAW.write_text(json.dumps(d, indent=1), encoding="utf-8")
    print(f"draw written: {d['lines_on_night']} lines on the night; sample {len(d['sample'])}, extension {len(d['extension'])}, decoys {len(d['decoys'])}")


def _items(extend: bool) -> tuple[list[dict], dict]:
    d = json.loads(DRAW.read_text(encoding="utf-8"))
    codes = page_codes(d, extend)
    items = [item(c, d["values"][c], d["decoys"]) for c in codes]
    key = {c: ("decoy" if c in d["decoys"] else "sample") for c in codes}
    return items, key


def cmd_photos() -> None:
    import fix_review_page as frp
    items, key = _items(True)
    (R / f"fix_review_{WHICH}_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    frp.cmd_photos(WHICH)


def cmd_html(extend: bool) -> None:
    import final_page as fp
    items, key = _items(extend)
    photos_all = json.loads((R / f"fix_review_{WHICH}_photos.json").read_text(encoding="utf-8"))
    photos = {c: photos_all.get(c, "") for c in key}
    (R / f"{WHICH}_key.json").write_text(json.dumps(key, indent=0), encoding="utf-8")
    out = R / f"{WHICH}_page.html"
    out.write_text(fp.render(items, photos, WHICH), encoding="utf-8")
    print("written", out, "| lines on the page", len(items), "| without a photo address:", sum(not v for v in photos.values()))


def cmd_join() -> None:
    key = json.loads((R / f"{WHICH}_key.json").read_text(encoding="utf-8"))
    answers = json.loads(ANSWERS.read_text(encoding="utf-8"))
    print(json.dumps(score(answers, key), indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["draw", "photos", "html", "join"])
    ap.add_argument("--lines")
    ap.add_argument("--night")
    ap.add_argument("--extend", action="store_true")
    a = ap.parse_args()
    if a.cmd == "draw":
        if not (a.lines and a.night):
            sys.exit("draw needs --lines and --night")
        cmd_draw(a.lines, a.night)
    elif a.cmd == "photos":
        cmd_photos()
    elif a.cmd == "html":
        cmd_html(a.extend)
    else:
        cmd_join()


if __name__ == "__main__":
    main()
