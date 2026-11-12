"""Round 2 of the photo-reading test: apply the rule, fix the random 70, build the ONE judging page, score the owner's answers (written 2026-11-11, after both readers ran, before any judging).

  python p8_steward/round2_page.py decide   -> output/review_set/round2_decisions.json (the rule applied to all 214 products) and round2_random70.json (never overwritten)
  python p8_steward/round2_page.py html     -> output/review_set/round2_items.json, round2_key.json (NOT in the page), round2_photos.json and round2_page.html (Save writes fix_review_round2_answers.json)
  python p8_steward/round2_page.py join     -> reads the answers: the full set (primary), the random 70 (check), by line type, the contributor beside it, sensitivities

The page shows EVERY shown line in ONE shuffled order, sha256('order-3:' + code); blind A/B = the photo table against the contributor's post-fix record, swapped by the parity of sha256('swap-3:' + code).
The random 70 are the first 70 shown lines in sha256('judge-2:' + code) order; they are derived and saved by `decide` before any judging and are not marked on the page.
Answers: the photo table is right when the owner chooses it or 'both'; 'neither' is wrong; "can't tell" is excluded and reported (and counted as wrong as a sensitivity).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_review_page as frp  # noqa: E402
import fix_test_lib as t  # noqa: E402
import photo_method as pm  # noqa: E402

R = frp.R
WHICH = "round2"
RANDOM_N = 70
PHOTOS = R / "photos_round2"
DECISIONS = R / "round2_decisions.json"
RANDOM70 = R / "round2_random70.json"
ANSWERS = R / "fix_review_round2_answers.json"
EXCLUDED = R / "round2_excluded.json"                  # code -> reason; set by the owner before any result is seen


def h(prefix: str, code: str) -> str:
    return hashlib.sha256((prefix + code).encode()).hexdigest()


def photo_first(code: str) -> bool:
    """True when the photo table is A (a hash, so the position tells nothing)."""
    return int(h("swap-3:", code), 16) % 2 == 0


def page_order(codes: list[str]) -> list[str]:
    return sorted(codes, key=lambda c: h("order-3:", c))


def random70(shown: list[str]) -> list[str]:
    return sorted(shown, key=lambda c: h("judge-2:", c))[:RANDOM_N]


def build_item(row: dict, table: dict, text_reading: dict | None, scan: dict | None) -> tuple[dict, dict]:
    p, c = frp.candidate_values(table), frp.candidate_values(t.key(row))
    first = photo_first(row["code"])
    a, b = (p, c) if first else (c, p)
    size, src = frp.serving_for_page(row, text_reading)
    item = {"code": row["code"], "A": a, "B": b, "stored_before": frp.candidate_values(t.before(row)), "serving": row.get("serving_size") or "", "serving_g": size, "serving_src": src,
            "basis_hint": (text_reading or {}).get("basis") or "", "glossary": frp.glossary_from_scan(scan)}
    return item, {"A": "photo" if first else "contributor", "B": "contributor" if first else "photo"}


def score(answers: dict, key: dict, decisions: dict, random_codes: list[str], excluded: dict | None = None) -> dict:
    """The owner's answers against the key. A line is 'photo right' when the owner chose the photo table or 'both'; 'unsure' is excluded (and reported); 'neither' is wrong.
    `excluded` = code -> reason: cases the owner took out BEFORE seeing any result, whatever the answer (a gap in OUR instruction, not a reader error). They leave every count, the full set and
    the random 70 alike, and are listed apart with the answer given, so that dropping a case never depends on whether the reader was right."""
    excluded = excluded or {}
    decisions = {c: d for c, d in decisions.items() if c not in excluded}
    def tally(codes):
        k = n = unsure = contributor_right = 0
        for c in codes:
            if c not in answers:
                continue
            a = answers[c]
            who = {"A": key[c]["A"], "B": key[c]["B"]}.get(a, a)
            if who == "unsure":
                unsure += 1
                continue
            n += 1
            k += who in ("photo", "both")
            contributor_right += who in ("contributor", "both")
        lo, hi = t.wilson(k, n)
        lo_u, _ = t.wilson(k, n + unsure)
        return {"judged": n, "photo_right": k, "rate": round(k / n, 3) if n else None, "wilson_95": [round(lo, 3), round(hi, 3)], "unsure": unsure,
                "wilson_lower_unsure_counted_wrong": round(lo_u, 3), "contributor_right": contributor_right}
    shown = [c for c, d in decisions.items() if d["table"] is not None]
    out = {"shown": len(shown), "answered": sum(c in answers for c in shown), "full_set": tally(shown), "random_70": tally([c for c in random_codes if c in decisions and decisions[c]["table"] is not None])}
    out["by_type"] = {ty: tally([c for c in shown if ty in decisions[c]["types"]]) for ty in pm.LINE_TYPES}
    out["excluded_apart"] = {c: {"reason": why, "answer_given": answers.get(c)} for c, why in excluded.items()}
    return out


def cmd_decide() -> None:
    import fix_test_agent as fa
    rows = json.loads((R / "fix_test_round2.json").read_text(encoding="utf8"))
    text_r = json.loads(fa.files("round2", pm.MODEL)[1].read_text(encoding="utf-8"))
    photo_r = json.loads((R / f"fix_test_photo_readings_round2__{pm.MODEL}.json").read_text(encoding="utf-8"))
    hybrids = {r["code"]: x for r, _, x, _ in frp.hybrid_records("round2")}
    out, silence = {}, {}
    for row in rows:
        code = row["code"]
        text = pm.ocr_text(code) if (R / "ocr_json" / f"{code}.json").exists() else ""
        d = pm.decide(code, text_r.get(code), photo_r.get(code), text, t.before(row), has_photo=(PHOTOS / f"{code}.jpg").exists(), hybrid=frp.candidate_values(hybrids[code]))
        out[code] = d
        if d["silence"]:
            silence[d["silence"]] = silence.get(d["silence"], 0) + 1
    DECISIONS.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf8")
    shown = [c for c, d in out.items() if d["table"] is not None]
    if RANDOM70.exists():
        print(RANDOM70.name, "exists: the random 70 is never re-derived")
    else:
        RANDOM70.write_text(json.dumps(random70(shown)), encoding="utf8")
    types = {ty: sum(ty in out[c]["types"] for c in shown) for ty in pm.LINE_TYPES}
    print(f"{len(rows)} products | lines shown {len(shown)} | silence {json.dumps(silence)} | line types {json.dumps(types)} | random 70 saved: {len(json.loads(RANDOM70.read_text(encoding='utf8')))}")


def data_uri(path: Path) -> str:
    """A photo as a data address, so the page needs no internet (the 'open in a new tab' link of the page does not work for these: browsers block opening a data address)."""
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def cmd_html(embed: bool = False) -> None:
    import fix_test_agent as fa
    rows = {r["code"]: r for r in json.loads((R / "fix_test_round2.json").read_text(encoding="utf8"))}
    dec = json.loads(DECISIONS.read_text(encoding="utf8"))
    text_r = json.loads(fa.files("round2", pm.MODEL)[1].read_text(encoding="utf-8"))
    addresses = json.loads((PHOTOS / "addresses.json").read_text(encoding="utf8"))
    items, key = [], {}
    for code in page_order([c for c, d in dec.items() if d["table"] is not None]):
        f = R / "ocr_json" / f"{code}.json"
        scan = json.loads(f.read_text(encoding="utf8")) if f.exists() and f.stat().st_size > 2 else None
        item, k = build_item(rows[code], dec[code]["table"], (text_r.get(code) or {}).get("reading"), scan)
        items.append(item)
        key[code] = k
    photos = {c: addresses.get(c, "") for c in key}
    (R / "round2_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf8")
    (R / "round2_key.json").write_text(json.dumps(key, indent=0), encoding="utf8")
    (R / "round2_photos.json").write_text(json.dumps(photos), encoding="utf8")
    if embed:
        missing = [c for c in key if not (PHOTOS / f"{c}.jpg").exists()]
        if missing:
            sys.exit(f"{len(missing)} local photos missing, e.g. {missing[:3]}: nothing written")
        photos = {c: data_uri(PHOTOS / f"{c}.jpg") for c in key}
    out = R / ("round2_page_offline.html" if embed else "round2_page.html")
    out.write_text(frp.render(items, photos, WHICH), encoding="utf8")
    print("written", out, f"({out.stat().st_size / 1e6:.1f} MB)", "| lines on the page", len(items), "| without a photo address:", sum(not v for v in photos.values()))


def cmd_join() -> None:
    key = json.loads((R / "round2_key.json").read_text(encoding="utf8"))
    dec = json.loads(DECISIONS.read_text(encoding="utf8"))
    answers = json.loads(ANSWERS.read_text(encoding="utf8"))
    excluded = json.loads(EXCLUDED.read_text(encoding="utf8")) if EXCLUDED.exists() else {}
    print(json.dumps(score(answers, key, dec, json.loads(RANDOM70.read_text(encoding="utf8")), excluded), indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decide", "html", "join"])
    ap.add_argument("--embed", action="store_true", help="html: put the local photos inside the page (round2_page_offline.html), no internet needed")
    a = ap.parse_args()
    {"decide": cmd_decide, "html": lambda: cmd_html(a.embed), "join": cmd_join}[a.cmd]()


if __name__ == "__main__":
    main()
