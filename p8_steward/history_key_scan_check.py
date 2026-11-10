"""Are the values OFF's fix history ends on printed on the pack? (no model, no key from the owner)

  python p8_steward/history_key_scan_check.py pick   [--n 150]      -> output/review_set/history_key_sample.json   (the sample, fixed before any scan is looked at)
  python p8_steward/history_key_scan_check.py report                 -> counts, from the scans in output/review_set/ocr_json/
  (the scans are fetched with: python p8_steward/bootstrap/fetch_ocr_json.py --part test --codes <codes>)

RULES (written 2026-11-08 before any scan of the sample was read): the candidates are the products of whole OFF for which a weekly step (12 Apr to 1 Nov 2026) removed every
nutrition error flag (not renamed, product edited) and changed at least one core per-100 value (history_fix_candidates.jsonl). The sample is the first n by sha256 of
'history-key-1:' + code. A fix is SUPPORTED when every value that changed is printed in the product's raw scan text (answer_key_lib.grounded_values: the number appears in the text,
also as milligrams for the gram fields). The same test on the old values is reported beside it. A product with no scan is counted as 'no scan' and left out of the rate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_key_lib as akl  # noqa: E402
import scan_layout  # noqa: E402

REVIEW = Path(__file__).resolve().parents[1] / "output" / "review_set"
MAP = {"energy_kj": "energy-kj", "energy_kcal": "energy-kcal", "fat": "fat", "saturated_fat": "saturated-fat", "carbohydrates": "carbohydrates", "sugars": "sugars",
       "fiber": "fiber", "proteins": "proteins", "salt": "salt", "sodium": "sodium"}
SALT = "history-key-1:"


def pick(candidates: list[dict], n: int) -> list[dict]:
    """The first n products by sha256 of a fixed salt plus the code (one row per code; a fixed rule, no random draw)."""
    seen, rows = set(), []
    for c in sorted(candidates, key=lambda c: hashlib.sha256((SALT + c["code"]).encode()).hexdigest()):
        if c["code"] not in seen:
            seen.add(c["code"])
            rows.append(c)
    return rows[:n]


def num(x):
    return None if x is None else float(x)


def side(row: dict, which: str) -> dict:
    out = {}
    for field, key in MAP.items():
        v = num(row.get(f"{which}_{key.replace('-', '_')}"))
        if v is not None:
            out[field] = v
    return out


def changed_fields(row: dict) -> list[str]:
    before, after = side(row, "a"), side(row, "b")
    return [f for f in MAP if ((f in before) != (f in after)) or (f in after and abs(after[f] - before[f]) > 1e-6 * max(1.0, abs(before[f])))]


def scan_text(scan: dict) -> str:
    return " ".join(w["text"] for w in scan_layout.words_of(scan))


def judge(row: dict, scan: dict) -> dict:
    fields = changed_fields(row)
    after = {f: v for f, v in side(row, "b").items() if f in fields}
    before = {f: v for f, v in side(row, "a").items() if f in fields}
    text = scan_text(scan)
    if not text:
        return {"code": row["code"], "status": "no_scan"}
    kept_after, _ = akl.grounded_values(after, text)
    kept_before, _ = akl.grounded_values(before, text)
    return {"code": row["code"], "status": "scanned", "changed": fields, "after_all_printed": bool(after) and len(kept_after) == len(after),
            "before_all_printed": bool(before) and len(kept_before) == len(before), "removed_only": not after}


def summarise(results: list[dict]) -> dict:
    scanned = [r for r in results if r["status"] == "scanned" and not r["removed_only"]]
    s = sum(r["after_all_printed"] for r in scanned)
    return {"sampled": len(results), "no_scan": sum(r["status"] == "no_scan" for r in results), "removed_only_skipped": sum(r.get("removed_only", False) for r in results),
            "scored": len(scanned), "supported_after_all_printed": s, "old_values_also_all_printed": sum(r["before_all_printed"] for r in scanned),
            "supported_and_old_not_printed": sum(r["after_all_printed"] and not r["before_all_printed"] for r in scanned)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pick", "report"])
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    if a.cmd == "pick":
        cands = [json.loads(line) for line in (REVIEW / "history_fix_candidates.jsonl").read_text(encoding="utf8").splitlines()]
        rows = pick(cands, a.n)
        (REVIEW / "history_key_sample.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf8")
        print(len(rows), "of", len(cands), "candidates; codes:", " ".join(r["code"] for r in rows))
        return
    rows = json.loads((REVIEW / "history_key_sample.json").read_text(encoding="utf8"))
    results = []
    for row in rows:
        f = REVIEW / "ocr_json" / f"{row['code']}.json"
        if not f.exists():
            results.append({"code": row["code"], "status": "not_fetched"})
            continue
        results.append(judge(row, json.loads(f.read_text(encoding="utf8"))))
    print("not fetched yet:", sum(r["status"] == "not_fetched" for r in results))
    print(json.dumps(summarise([r for r in results if r["status"] != "not_fetched"])))
    for r in results:
        if r["status"] == "scanned" and not r["removed_only"] and not r["after_all_printed"]:
            print("not supported:", r["code"], r["changed"])


if __name__ == "__main__":
    main()
