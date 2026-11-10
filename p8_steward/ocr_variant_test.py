"""Does a cleaner text of the nutrition photo make the reader better? (development test on the owner's 85 blind judgments; no labelling, no sealed data)

  python p8_steward/ocr_variant_test.py texts  --variant layout|block|v0            -> output/review_set/ocr_variants/text_<variant>.json (derived text only)
  python p8_steward/ocr_variant_test.py run    --variant <name> [--limit N]         -> Gemini reads each text; output/review_set/ocr_variants/readings_<variant>.json (resumable)
  python p8_steward/ocr_variant_test.py score  --variant <name> [--variant ...]     -> the metric below, no model call

THE METRIC (fixed before any variant was run). Cases = the owner's judged round-1 products (answers A/B/both/neither; 'can't tell' dropped). For every case where the owner found a table right
(contributor's, hybrid's or both: 64 cases) that table is the TRUTH. The reader's reading (values not printed in the variant's text are dropped, as in the method; a per-serving column is
converted by the serving size in g or ml) is RIGHT when it agrees with the truth on at least 90% of at least 3 shared fields (10% rule, answer_key_lib.field_matches). Reported: usable readings,
right of the 64, right among usable, and the same on the 17 'neither' cases as 'usable' only (no truth there). The prompt, the model and the settings are the frozen reader's; only the TEXT changes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
import dev_ocr_reader as dr  # noqa: E402
import gateway as gw  # noqa: E402
import reader_decision as rd  # noqa: E402
import scan_layout2 as sl2  # noqa: E402

R = ROOT / "output" / "review_set"
OUT = R / "ocr_variants"
MODEL = "gemini-3.5-flash-lite"
FIELDS = ("energy_kcal", "energy_kj", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt", "sodium")
TEXT_CAP = 9000
PAUSE = 5


def agree(x: dict, y: dict, thr: float = 0.9, min_fields: int = 3) -> bool:
    shared = [f for f in FIELDS if f in x and f in y]
    return len(shared) >= min_fields and sum(akl.field_matches(f, x[f], y[f]) for f in shared) / len(shared) >= thr


def verdict(answer: str, key_entry: dict) -> str:
    """The owner's answer as who was right: hybrid | contributor | both | neither | unsure."""
    return {"A": key_entry["A"], "B": key_entry["B"]}.get(answer, answer)


def truth_table(who: str, hybrid: dict, contributor: dict):
    """The table the owner found right (the contributor's for 'both'); None when there is none."""
    return {"hybrid": hybrid, "contributor": contributor, "both": contributor}.get(who)


def judged_cases() -> list[dict]:
    answers = json.loads((R / "fix_review_round1_answers.json").read_text(encoding="utf8"))
    key = json.loads((R / "fix_review_round1_key.json").read_text(encoding="utf8"))
    items = {i["code"]: i for i in json.loads((R / "fix_review_round1_items.json").read_text(encoding="utf8"))}
    cases = []
    for code, a in answers.items():
        who = verdict(a, key[code])
        if who == "unsure":
            continue
        it = items[code]
        side = lambda src: it["A"] if key[code]["A"] == src else it["B"]      # noqa: E731
        cases.append({"code": code, "who": who, "truth": truth_table(who, side("hybrid"), side("contributor")), "basis": it["basis_hint"] or "(none)"})
    return cases


def scan_json(code: str) -> dict:
    f = R / "ocr_json" / f"{code}.json"
    return json.loads(f.read_text(encoding="utf8")) if f.exists() and f.stat().st_size > 2 else {}


def text_for(variant: str, code: str) -> str:
    """The text a variant gives the reader for one product (empty when it has none)."""
    if variant == "v0":
        return dr.scan_text(code, "v3rows")
    if variant == "layout":
        return sl2.layout_text(sl2.google_words(scan_json(code)))
    if variant == "block":
        return sl2.block_text(sl2.google_words(scan_json(code)))
    f = OUT / f"text_{variant}.json"                                          # engine variants are built into a text file by the engine scripts
    return json.loads(f.read_text(encoding="utf8")).get(code, "")


def build_texts(variant: str) -> None:
    OUT.mkdir(exist_ok=True)
    texts = {c["code"]: text_for(variant, c["code"]) for c in judged_cases()}
    (OUT / f"text_{variant}.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf8")
    print(variant, "texts:", sum(bool(t) for t in texts.values()), "of", len(texts), "non-empty; median chars", sorted(len(t) for t in texts.values())[len(texts) // 2])


def engine_texts(variant: str, boxes_file: str) -> None:
    """Turn another OCR engine's boxes ({code: [[text, four corner points, score], ...]}) into layout text with the same renderer, so only the ENGINE differs between variants."""
    boxes = json.loads(Path(boxes_file).read_text(encoding="utf8"))
    OUT.mkdir(exist_ok=True)
    texts = {}
    for c in judged_cases():
        raw = [(t, 0, [tuple(p) for p in pts]) for t, pts, *_ in boxes.get(c["code"], []) if t and len(pts) == 4]
        texts[c["code"]] = sl2.layout_text(sl2.straighten(raw))
    (OUT / f"text_{variant}.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf8")
    print(variant, "texts:", sum(bool(t) for t in texts.values()), "of", len(texts), "non-empty; median chars", sorted(len(t) for t in texts.values())[len(texts) // 2])


def run(variant: str, limit: int, env_file: str) -> None:
    sys.path.insert(0, str(ROOT / "p8_steward"))
    import fix_test_agent as fa
    texts = json.loads((OUT / f"text_{variant}.json").read_text(encoding="utf8"))
    out_file = OUT / f"readings_{variant}.json"
    done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    gateway, new = fa.make_gateway(MODEL, env_file), 0
    for code, text in texts.items():
        if code in done:
            continue
        if limit and new >= limit:
            break
        text = text[:TEXT_CAP]
        if not akl.text_has_table(text):
            done[code] = {"answer": "", "reading": None, "tokens": 0, "skipped": "no readable table in the text"}
            continue
        messages = [{"role": "system", "content": dr.SYSTEMS["v3rows"]}, {"role": "user", "content": f"<ocr>\n{text}\n</ocr>"}]
        try:
            res = gateway.call("steward", messages)
        except gw.GatewayError as e:
            print(code, "STOP", e.kind, str(e)[:300], e.retry_after)
            break
        new += 1
        done[code] = {"answer": res["text"], "reading": dr.read_json(res["text"]), "tokens": res["provenance"]["total_tokens"]}
        time.sleep(PAUSE)
        second = dr.retry_if_needed(gateway, messages, done[code], text)
        if second:
            done[code] = {**second, "first": {"answer": done[code]["answer"], "reading": done[code]["reading"]}, "tokens": done[code]["tokens"] + second["tokens"]}
        out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(code, "ok", done[code]["tokens"], "tokens", flush=True)
        time.sleep(PAUSE)
    out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(done)} readings saved ({new} new calls); tokens {sum(v['tokens'] for v in done.values())}")


def reading_of(entry: dict, text: str) -> dict | None:
    """The reading as per-100 numbers after the method's own guard (a value not printed in the text is dropped); None when unusable."""
    grounded, _ = rd.grounded_reading(entry.get("reading"), text[:TEXT_CAP])
    conv = akl.reading_to_per100(grounded)
    return conv["per100"] if conv["usable"] and len(conv["per100"]) >= 3 else None


def score(variant: str, cases: list[dict] | None = None) -> dict:
    cases = cases if cases is not None else judged_cases()
    texts = json.loads((OUT / f"text_{variant}.json").read_text(encoding="utf8")) if variant != "v0" else {c["code"]: text_for("v0", c["code"]) for c in cases}
    if variant == "v0":
        readings = json.loads((R / "fix_test_readings_round1__gemini-3.5-flash-lite.json").read_text(encoding="utf-8"))
    else:
        readings = json.loads((OUT / f"readings_{variant}.json").read_text(encoding="utf-8"))
    out = {"known_right": 0, "usable": 0, "right": 0, "neither_usable": 0, "neither": 0, "by_basis": {}}
    for c in cases:
        got = reading_of(readings.get(c["code"]) or {}, texts.get(c["code"], ""))
        if c["truth"] is None:
            out["neither"] += 1
            out["neither_usable"] += got is not None
            continue
        out["known_right"] += 1
        b = out["by_basis"].setdefault(c["basis"], {"n": 0, "right": 0})
        b["n"] += 1
        if got is not None:
            out["usable"] += 1
            ok = agree(got, c["truth"])
            out["right"] += ok
            b["right"] += ok
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["texts", "engine-texts", "run", "score"])
    ap.add_argument("--boxes", help="engine-texts: the engine's boxes file")
    ap.add_argument("--variant", action="append", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args()
    for v in a.variant:
        if a.cmd == "texts":
            build_texts(v)
        elif a.cmd == "engine-texts":
            engine_texts(v, a.boxes)
        elif a.cmd == "run":
            run(v, a.limit, a.env_file)
        else:
            s = score(v)
            n = s["known_right"]
            print(f"{v:14s} cases with a known-right table {n} | usable {s['usable']} ({s['usable']/n:.0%}) | right {s['right']} ({s['right']/n:.0%} of {n}; {s['right']/max(s['usable'],1):.0%} of usable) | "
                  f"'neither' cases usable {s['neither_usable']}/{s['neither']} | " + "; ".join(f"{k}: {b['right']}/{b['n']}" for k, b in sorted(s['by_basis'].items())))


if __name__ == "__main__":
    main()
