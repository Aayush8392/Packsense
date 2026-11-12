"""Final block, batch A: apply the rule, draw the lines to judge, build the ONE-LINE judging page, score the answers (written 2026-11-13, after both readers ran, before any judging).
The rules are in output/review_set/freeze_final.json ('preregistration'); this file follows them.

  python p8_steward/final_page.py decide   -> final_a_decisions.json (the rule on the 200 products) and final_a_draw.json (the sample, the decoys, the page order); never overwritten
  python p8_steward/final_page.py html     -> final_a_items.json, final_a_key.json (NOT in the page), final_a_photos.json and final_a_page.html (Save writes fix_review_final_a_answers.json)
  python p8_steward/final_page.py join     -> reads the answers: the sampled lines against the bar, the can't-tell sensitivity, the decoys, the excluded packs, the branch

The owner sees one line at a time: the photo and our line (the photo table) only. Answers: right / wrong / can't tell. Photos load from Open Food Facts; the page fetches the next two ahead.
Sample = the first 100 rule2 lines in sha256('final-judge:' + code) order; decoys = the first 15 of the other rule2 lines that print kcal, in sha256('final-decoy:' + code) order, each shown with its
kcal x 1.5 (rounded) so that the right answer is 'wrong'; page order = sha256('final-order:' + code). Decoys never enter the accuracy tally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_review_page as frp  # noqa: E402
import fix_test_lib as t  # noqa: E402
import photo_method as pm  # noqa: E402

R = frp.R
WHICH = "final_a"
SAMPLE_N, DECOY_N = 100, 15
PHOTOS = R / "photos_final"
DECISIONS = R / "final_a_decisions.json"
DRAW = R / "final_a_draw.json"
ANSWERS = R / "fix_review_final_a_answers.json"
EXCLUDED = R / "final_a_excluded.json"                  # code -> reason; set by the owner before any result is seen
DECOY_FACTOR = 1.5


def h(prefix: str, code: str) -> str:
    return hashlib.sha256((prefix + code).encode()).hexdigest()


def draw(shown: dict[str, dict]) -> dict:
    """shown = code -> the line's values (candidate_values of the photo table) for every rule2 line. Returns {'sample', 'decoys', 'order'}; pure and repeatable."""
    by_judge = sorted(shown, key=lambda c: h("final-judge:", c))
    sample = by_judge[:SAMPLE_N]
    pool = sorted((c for c in by_judge[SAMPLE_N:] if shown[c].get("energy_kcal") is not None), key=lambda c: h("final-decoy:", c))
    decoys = {c: {"original_kcal": shown[c]["energy_kcal"], "shown_kcal": round(shown[c]["energy_kcal"] * DECOY_FACTOR)} for c in pool[:DECOY_N]}
    order = sorted(list(sample) + list(decoys), key=lambda c: h("final-order:", c))
    return {"sample": sample, "decoys": decoys, "order": order}


def cmd_decide() -> None:
    import fix_test_agent as fa
    rows = json.loads((R / "fix_test_final_a.json").read_text(encoding="utf8"))
    text_r = json.loads(fa.files("final_a", pm.MODEL)[1].read_text(encoding="utf-8"))
    photo_r = json.loads((R / f"fix_test_photo_readings_final_a__{pm.MODEL}.json").read_text(encoding="utf-8"))
    out, silence = {}, {}
    for row in rows:
        code = row["code"]
        text = pm.ocr_text(code) if (R / "ocr_json" / f"{code}.json").exists() else ""
        d = pm.decide(code, text_r.get(code), photo_r.get(code), text, t.before(row), has_photo=(PHOTOS / f"{code}.jpg").exists())
        out[code] = d
        if d["silence"]:
            silence[d["silence"]] = silence.get(d["silence"], 0) + 1
    if DRAW.exists():
        print(DRAW.name, "exists: the draw is never re-derived")
    else:
        DECISIONS.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf8")
        shown = {c: frp.candidate_values(d["table"]) for c, d in out.items() if d["rule2"] and d["table"] is not None}
        DRAW.write_text(json.dumps(draw(shown), indent=0), encoding="utf8")
    dr = json.loads(DRAW.read_text(encoding="utf8"))
    print(f"{len(rows)} products | rule2 lines {sum(1 for d in out.values() if d['rule2'] and d['table'] is not None)} | silence {json.dumps(silence)} | sample {len(dr['sample'])} | decoys {len(dr['decoys'])}")


def build_item(row: dict, values: dict, text_reading: dict | None, scan: dict | None) -> dict:
    size, src = frp.serving_for_page(row, text_reading)
    return {"code": row["code"], "A": values, "B": {}, "stored_before": {}, "serving": row.get("serving_size") or "", "serving_g": size, "serving_src": src,
            "basis_hint": (text_reading or {}).get("basis") or "", "glossary": frp.glossary_from_scan(scan)}


DARK_CSS = """
body.dark{background:#17181a;color:#e6e6e3}body.dark header{background:#000}
body.dark table{background:#222;border-color:#444;color:#e6e6e3}body.dark th{background:#2d2f31}body.dark td{border-top-color:#333}
body.dark .choices label{background:#222;border-color:#555;color:#e6e6e3}body.dark .choices label.sel{background:#1c2f55;border-color:#6ea0ff}
body.dark button{background:#2a2b2d;color:#e6e6e3;border-color:#666}body.dark #tools button{background:rgba(40,40,40,.92);color:#eee}
body.dark .gloss{background:#222;border-color:#444;color:#ddd}body.dark .gloss .note,body.dark .meta{color:#aaa}body.dark #photo{border-color:#444}
body.dark a{color:#9cc2ff}
"""
INTRO = ("Look at the photo, then say whether OUR line below matches what the pack prints (per 100 g or 100 ml). Only printed values decide: "
         "a value the pack does not print is neutral.")


def right_html(intro: str = INTRO) -> str:
    return '<div id="right"><div class="meta">' + intro + '</div><b>Our line</b><table id="ta"></table><div class="meta" id="stmt"></div><div class="choices" id="choices"></div></div></main>'


CHOICES = 'const CH=[["right","1","Our line matches the pack"],["wrong","2","Our line does not match the pack"],["unsure","3","I can\'t tell (blurry, per serving only, ...)"]];'
DARK_JS = ('const dk=()=>{try{return localStorage.getItem("fixreview_dark")}catch(e){return null}};'
           'function setDark(on){document.body.classList.toggle("dark",on);$("dark").textContent=on?"Light mode":"Dark mode";try{localStorage.setItem("fixreview_dark",on?"1":"0")}catch(e){}}'
           'setDark(dk()==="1"||(dk()===null&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches));$("dark").onclick=()=>setDark(!document.body.classList.contains("dark"));\n')


def render(items: list[dict], photos: dict, which: str = WHICH, choices: str | None = None, intro: str | None = None) -> str:
    """choices: the JS text of the answer list (default CHOICES); intro: the sentence above the table. An item may carry a 'statement' shown under the table."""
    page = frp.render(items, photos, which)

    def sub(old: str, new: str, regex: bool = False) -> None:
        nonlocal page
        if regex:
            page, n = re.subn(old, lambda _m: new, page, count=1, flags=re.S)
            assert n == 1, old
        else:
            assert page.count(old) == 1, old
            page = page.replace(old, new)

    sub("<title>Which table matches the pack?</title>", "<title>Does this line match the pack?</title>")
    sub("</style></head>", DARK_CSS + "</style></head>")
    sub('<button id="save">Save answers</button>', '<button id="dark">Dark mode</button><button id="save">Save answers</button>')
    sub(r'<div id="right">.*?</details></div></main>', right_html(intro or INTRO), regex=True)
    sub(r'const CH=\[.*?\];', choices or CHOICES, regex=True)
    sub('tab($("ta"),it.A,it.B,it.serving_g);tab($("tb"),it.B,it.A,it.serving_g);tab($("tc"),it.stored_before,null,it.serving_g);', 'tab($("ta"),it.A,null,it.serving_g);$("stmt").textContent=it.statement||"";')
    sub("show();\n</script>", DARK_JS + "show();\n</script>")
    return page


def cmd_html() -> None:
    import fix_test_agent as fa
    rows = {r["code"]: r for r in json.loads((R / "fix_test_final_a.json").read_text(encoding="utf8"))}
    dec = json.loads(DECISIONS.read_text(encoding="utf8"))
    dr = json.loads(DRAW.read_text(encoding="utf8"))
    text_r = json.loads(fa.files("final_a", pm.MODEL)[1].read_text(encoding="utf-8"))
    addresses = json.loads((PHOTOS / "addresses.json").read_text(encoding="utf8"))
    items, key = [], {}
    for code in dr["order"]:
        f = R / "ocr_json" / f"{code}.json"
        scan = json.loads(f.read_text(encoding="utf8")) if f.exists() and f.stat().st_size > 2 else None
        values = frp.candidate_values(dec[code]["table"])
        if code in dr["decoys"]:
            values["energy_kcal"] = dr["decoys"][code]["shown_kcal"]
        items.append(build_item(rows[code], values, (text_r.get(code) or {}).get("reading"), scan))
        key[code] = "decoy" if code in dr["decoys"] else "sample"
    photos = {c: addresses.get(c, "") for c in key}
    (R / "final_a_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf8")
    (R / "final_a_key.json").write_text(json.dumps(key, indent=0), encoding="utf8")
    (R / "final_a_photos.json").write_text(json.dumps(photos), encoding="utf8")
    out = R / "final_a_page.html"
    out.write_text(render(items, photos), encoding="utf8")
    print("written", out, f"({out.stat().st_size / 1e6:.1f} MB)", "| lines on the page", len(items), "| without a photo address:", sum(not v for v in photos.values()))


def score(answers: dict, key: dict, excluded: dict | None = None) -> dict:
    """answers: code -> right / wrong / unsure. key: code -> 'sample' or 'decoy'. `excluded` (code -> reason; set before any result) leaves every count and is listed apart with the answer given."""
    excluded = excluded or {}
    sample = [c for c, k in key.items() if k == "sample" and c not in excluded]
    decoys = [c for c, k in key.items() if k == "decoy" and c not in excluded]
    right = sum(answers.get(c) == "right" for c in sample)
    wrong = sum(answers.get(c) == "wrong" for c in sample)
    unsure = sum(answers.get(c) == "unsure" for c in sample)
    n = right + wrong
    lo, hi = t.wilson(right, n) if n else (0.0, 0.0)
    lo_u, _ = t.wilson(right, n + unsure) if n + unsure else (0.0, 0.0)
    branch = "pass" if lo >= 0.80 else ("extension: read batch B and judge 100 more lines" if lo >= 0.70 else "fail")
    return {"sample_lines": len(sample), "answered": sum(c in answers for c in sample), "right": right, "wrong": wrong, "unsure": unsure,
            "rate": round(right / n, 3) if n else None, "wilson_95": [round(lo, 3), round(hi, 3)], "wilson_lower_unsure_counted_wrong": round(lo_u, 3), "branch_if_complete": branch,
            "decoys": {"lines": len(decoys), "caught_as_wrong": sum(answers.get(c) == "wrong" for c in decoys), "missed_as_right": sum(answers.get(c) == "right" for c in decoys),
                       "unsure": sum(answers.get(c) == "unsure" for c in decoys), "unanswered": sum(c not in answers for c in decoys)},
            "excluded_apart": {c: {"reason": why, "answer_given": answers.get(c)} for c, why in excluded.items()}}


def cmd_join() -> None:
    key = json.loads((R / "final_a_key.json").read_text(encoding="utf8"))
    answers = json.loads(ANSWERS.read_text(encoding="utf8"))
    excluded = json.loads(EXCLUDED.read_text(encoding="utf8")) if EXCLUDED.exists() else {}
    print(json.dumps(score(answers, key, excluded), indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decide", "html", "join"])
    a = ap.parse_args()
    {"decide": cmd_decide, "html": cmd_html, "join": cmd_join}[a.cmd]()


if __name__ == "__main__":
    main()
