"""Guard v2 on the SAVED readings of round 2 and of the final block's batch A (no model call). Pre-registered in output/review_set/guard_and_statements_prereg.md.

  python p8_steward/guard_v2_experiment.py run   -> output/review_set/guard_v2_results.json and a printed summary

Which lines are shown is unchanged (original guard and frozen agreement); v2 only adds values to a shown line: the lines that gain values and the values recovered per rule are reported.
Nothing already reported changes: the saved decisions files are only read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_test_agent as fa  # noqa: E402
import fix_test_lib as t  # noqa: E402
import guard_v2 as g  # noqa: E402
import ocr_variant_test as ov  # noqa: E402
import photo_method as pm  # noqa: E402

R = ROOT / "output" / "review_set"
OUT = R / "guard_v2_results.json"
SETS = {"round2": ("fix_test_round2.json", "photos_round2", "round2"), "final_a": ("fix_test_final_a.json", "photos_final", "final_a")}


def load(name: str) -> tuple[list, dict, dict, Path, str]:
    rows_file, photos, which = SETS[name]
    rows = json.loads((R / rows_file).read_text(encoding="utf8"))
    text_r = json.loads(fa.files(which, pm.MODEL)[1].read_text(encoding="utf-8"))
    photo_r = json.loads((R / f"fix_test_photo_readings_{which}__{pm.MODEL}.json").read_text(encoding="utf-8"))
    return rows, text_r, photo_r, R / photos, which


def main() -> None:
    """Design: WHICH lines are shown is decided exactly as before (the original guard on both readings, the frozen agreement rule); v2 only ENRICHES a shown line with values the photo
    reader read and the OCR confirms by the v2 rules. Reason (seen on the first run): applying v2 to both readings let the text reader's copy of the OCR error (0.39, 589) disagree with the
    photo's right value (0.3, 58) and silenced 6 lines that were right."""
    if len(sys.argv) < 2 or sys.argv[1] != "run":
        sys.exit(__doc__)
    results = {}
    for name in SETS:
        rows, text_r, photo_r, photos, _ = load(name)
        gained, by_rule = {}, {}
        shown = 0
        for row in rows:
            c = row["code"]
            text = pm.ocr_text(c) if (R / "ocr_json" / f"{c}.json").exists() else ""
            d = pm.decide(c, text_r.get(c), photo_r.get(c), text, t.before(row), has_photo=(photos / f"{c}.jpg").exists())
            if not (d["rule2"] and d["table"] is not None):
                continue
            shown += 1
            g.LOG.clear()
            with g.installed():
                new = ov.reading_of(photo_r[c], text)
            extra = {f: v for f, v in (new or {}).items() if f not in d["table"] and v is not None}
            if extra:
                gained[c] = {"added": extra, "evidence": [dict(e) for e in g.LOG if e["field"] in extra or any(abs(e["value"] - extra.get(k, -1)) < 1e-9 for k in extra)]}
                for e in gained[c]["evidence"]:
                    by_rule[e["rule"]] = by_rule.get(e["rule"], 0) + 1
        results[name] = {"products": len(rows), "shown_lines": shown, "lines_gaining_values": gained, "values_added": sum(len(v["added"]) for v in gained.values()), "recoveries_by_rule": by_rule}
        print(name, {k: (len(v) if isinstance(v, dict) and k == "lines_gaining_values" else v) for k, v in results[name].items() if k != "lines_gaining_values"}, "| lines gaining values", len(gained))
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf8")
    print("written", OUT.name)


if __name__ == "__main__":
    main()
