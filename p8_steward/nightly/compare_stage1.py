"""One-off: compares a scratch night (stage 1) with the saved final-block decisions of batch A, product by product. Prints counts and the differing barcodes (local use only, never in a log).

  python p8_steward/nightly/compare_stage1.py --night 2026-11-13 --queue queue.json --lines lines_night.json --run run_night.json

The three night files are downloaded by hand from the scratch dataset (`queue.json`, `lines/<night>.json`, `runs/<night>.json`; rename the last two, they share a name).
For every product the night finished (done in the queue with that night's date) it tells whether a line was shown, was silent, and whether the saved decision agrees; for lines shown in both, whether
the two tables agree on the shared fields (the frozen 10% rule, photo_method's agreement) and which fields differ exactly. Differences are listed, not judged: the reading runs at temperature 0.2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import ocr_variant_test as ov  # noqa: E402

R = ROOT / "output" / "review_set"


def compare(queue: dict, lines: list[dict], run: dict, decisions: dict, night: str) -> dict:
    shown = {ln["code"]: ln for ln in lines}
    out = {"night": night, "stopped": run.get("stopped"), "canary": run.get("canary"), "calls": run.get("calls"), "finished": 0, "no_saved_decision": 0,
           "both_shown": 0, "both_silent": 0, "only_saved_shows": [], "only_night_shows": [], "tables_agree": 0, "tables_differ": [], "exact_on_shared": 0, "night_silences": {}}
    for code, d in sorted(queue["done"].items()):
        if d["night"] != night:
            continue
        out["finished"] += 1
        saved = decisions.get(code)
        if saved is None:
            out["no_saved_decision"] += 1
            continue
        saved_shows = bool(saved.get("rule2") and saved.get("table"))
        night_shows = d["outcome"] == "line" and code in shown
        if d["outcome"] == "silence":
            out["night_silences"][d["reason"]] = out["night_silences"].get(d["reason"], 0) + 1
        if saved_shows and night_shows:
            out["both_shown"] += 1
            new, old = shown[code]["values"], {f: v for f, v in saved["table"].items() if v is not None}
            if ov.agree(new, old):
                out["tables_agree"] += 1
            else:
                out["tables_differ"].append(code)
            if all(new[f] == old[f] for f in new if f in old):
                out["exact_on_shared"] += 1
        elif saved_shows:
            out["only_saved_shows"].append({"code": code, "night": d["reason"] or d["outcome"]})
        elif night_shows:
            out["only_night_shows"].append(code)
        else:
            out["both_silent"] += 1
    decided = out["both_shown"] + out["both_silent"] + len(out["only_saved_shows"]) + len(out["only_night_shows"])
    out["same_show_or_silence"] = out["both_shown"] + out["both_silent"]
    out["share_same"] = round(out["same_show_or_silence"] / decided, 3) if decided else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--night", required=True)
    ap.add_argument("--queue", required=True)
    ap.add_argument("--lines", required=True)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
    print(json.dumps(compare(load(a.queue), load(a.lines), load(a.run), load(R / "final_a_decisions.json"), a.night), indent=1))


if __name__ == "__main__":
    main()
