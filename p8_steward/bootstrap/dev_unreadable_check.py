"""Development check (item 23): what does the reader (version v3rows) do on the cards the OWNER could not read?

  python p8_steward/bootstrap/dev_unreadable_check.py --dry                 counts only: which of the cards have a raw scan and a table in it; no model call, no tokens
  python p8_steward/bootstrap/dev_unreadable_check.py --run [--env-file .env]    one call per card that has a table, through the gateway (about 1,100 tokens each)

The cards are the unusable ones of the development keys (dev and dev2): the owner could not read the table, or the pack prints per serving only with no serving size in g or ml. They have no
answer key, so nothing is scored right or wrong. The question is behavioural: the pack-text rule is that the check says 'not assessed' when the pack cannot be read, so every card on which the
reader ACTS (proposes a change or a fill-in, or says 'no change') is a case to look at by hand. DEVELOPMENT parts only; the test part is never run through this.
Output: output/review_set/dev_unreadable_v3rows.json (gitignored). Prints counts and barcodes of the development cards only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(HERE))
import answer_key_lib as ak  # noqa: E402
import dev_ocr_reader as dr  # noqa: E402
import fix_candidates as fc  # noqa: E402
import gateway as gw  # noqa: E402

SET = ROOT / "output" / "review_set"
PARTS = ("dev", "dev2")                       # development parts only
VERSION = "v3rows"
OUT = SET / "dev_unreadable_v3rows.json"


def unreadable_cards(key_cards: dict) -> dict:
    """The cards the owner could not use, by barcode."""
    return {c: e for c, e in key_cards.items() if not e["usable"]}


def all_unreadable(parts: tuple = PARTS) -> dict:
    out = {}
    for part in parts:
        key = json.loads((SET / f"answer_key_{part}_key.json").read_text(encoding="utf-8"))["cards"]
        for code, entry in unreadable_cards(key).items():
            out[code] = {**entry, "part": part}
    return out


def stored_rows() -> dict:
    rows_by: dict = {}
    for line in (SET / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["code"] not in rows_by or r["last_modified_t"] > rows_by[r["code"]]["last_modified_t"]:
                rows_by[r["code"]] = r
    return rows_by


def status(code: str) -> tuple[str, str]:
    """(state, text): 'no scan', 'no table' or 'table', with the rebuilt rows text the reader would see."""
    text = dr.scan_text(code, VERSION)[:6000]
    if not text.strip():
        return "no scan", text
    return ("table" if ak.text_has_table(text) else "no table"), text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--part", choices=["test"], help="run the sealed TEST part's unreadable cards instead (counts only, no barcodes printed; output dev_unreadable_v3rows_test.json)")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args()
    if a.dry == a.run:
        sys.exit("give exactly one of --dry and --run")
    test = a.part == "test"
    out_file = SET / "dev_unreadable_v3rows_test.json" if test else OUT
    cards = all_unreadable(("test",) if test else PARTS)
    states = {c: status(c) for c in cards}
    print(f"{len(cards)} unreadable cards ({Counter(e['part'] for e in cards.values())}); scan state: {dict(Counter(s for s, _ in states.values()))}")
    if a.dry:
        print(f"model calls a run would make: {sum(s == 'table' for s, _ in states.values())} (about {1100 * sum(s == 'table' for s, _ in states.values())} tokens)")
        return
    rows_by = stored_rows()
    gateway = gw.Gateway(gw.read_key("GROQ_API_KEY", a.env_file), usage=gw.UsageLog(ROOT / "output" / "gateway_usage.jsonl"))
    done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    for code, entry in cards.items():
        state, text = states[code]
        if code in done:
            continue
        if state != "table":
            done[code] = {"state": state, "action": "not assessed (no readable table in the scan)", "tokens": 0}
            continue
        messages = [{"role": "system", "content": dr.SYSTEMS[VERSION]}, {"role": "user", "content": f"<ocr>\n{text}\n</ocr>"}]
        try:
            res = gateway.call("steward", messages)
        except gw.GatewayError as e:
            print("STOP" if test else code, e.kind, str(e)[:500], e.retry_after)
            break
        first = {"answer": res["text"], "reading": dr.read_json(res["text"]), "tokens": res["provenance"]["total_tokens"]}
        time.sleep(13)
        second = dr.retry_if_needed(gateway, messages, first, text)            # only for unusable JSON; the feedback retry is off
        final = {**second, "tokens": first["tokens"] + second["tokens"]} if second else first
        stored = fc.clean(rows_by[code])
        d = dr.decide(stored, final["reading"], text, entry["group"], VERSION)
        done[code] = {"state": state, "action": d["action"], "tokens": final["tokens"], "dropped": d["dropped"]}
        out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print("." if test else f"{code} {entry['part']} -> {d['action'][:70]}", flush=True)
        time.sleep(13)
    out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    acted = [c for c, v in done.items() if not v["action"].startswith(("abstain", "not assessed"))]
    print(f"\n{len(done)} of {len(cards)} cards done; tokens used: {sum(v['tokens'] for v in done.values())}")
    print("actions:", dict(Counter(v["action"].split(' (')[0][:40] for v in done.values())))
    print(f"cards on which the reader ACTED (should be looked at by hand): {len(acted)}", [] if test else acted)


if __name__ == "__main__":
    main()
