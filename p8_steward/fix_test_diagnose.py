"""Where does the reader lose? For every development product the agent did not agree on, separate the READING (what the model took from the scan) from the DECISION (what code did with it).

  python p8_steward/fix_test_diagnose.py --model gemini-3.5-flash-lite [--show N]

Per product: does the reading itself agree with the fix key on the group's fields ('read_ok'); is the key printed in the scan ('key_printed'); did the decision keep or drop the reading.
No model call. Development slice only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
import dev_ocr_reader as dr  # noqa: E402
import fix_test_agent as fa  # noqa: E402
import fix_test_lib as t  # noqa: E402
import reader_decision as rd  # noqa: E402


def diagnose(model: str, which: str = "dev") -> list[dict]:
    rows_file, out_file = fa.files(which, model)
    rows = json.loads(rows_file.read_text(encoding="utf8"))
    readings = json.loads(out_file.read_text(encoding="utf-8"))
    out = []
    for row in rows:
        entry = readings.get(row["code"], {})
        text = dr.scan_text(row["code"], fa.VERSION)[:6000]
        group = t.group_of_row(row)
        dec = rd.decide(t.before(row), entry.get("reading"), text, group, fa.VERSION)
        cls = t.classify(row, t.agent_proposal(dec))
        read = dec.get("reading100") or {}
        gf = akl.GROUP_FIELDS[group]
        key_g = {f: v for f, v in t.key(row).items() if f in gf}
        read_ok = bool(read) and akl.matches_key(read, key_g)["match"] if key_g else None
        kept, dropped = akl.grounded_values(key_g, text) if key_g else ({}, [])
        out.append({"code": row["code"], "group": group, "class": cls, "action": dec["action"], "clean_key": t.clean_key(row), "has_reading": bool(read),
                    "read_ok": read_ok, "key_printed": bool(key_g) and not dropped, "dropped_by_guard": dec.get("dropped", []), "no_table": not akl.text_has_table(text)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--set", default="dev", dest="which")
    a = ap.parse_args()
    res = diagnose(a.model, a.which)
    for label, sel in (("CLEAN KEY", [r for r in res if r["clean_key"]]), ("ALL", res)):
        print(f"--- {label}: {len(sel)} products; agent not agreeing: {sum(r['class'] != 'agrees' for r in sel)}")
        miss = [r for r in sel if r["class"] != "agrees"]
        buckets: dict[str, list[str]] = {}
        for r in miss:
            if r["no_table"]:
                b = "A  no readable table in the scan"
            elif not r["has_reading"]:
                b = "B  no usable reading (" + r["action"][:45] + ")"
            elif r["read_ok"]:
                b = "C  READING AGREES with the key, the decision lost it (" + r["action"][:40] + ")"
            elif r["key_printed"]:
                b = "D  reading differs from the key, key IS printed in the scan (reader error)"
            else:
                b = "E  reading differs from the key, key NOT printed in the scan (key or scan unreliable)"
            buckets.setdefault(b, []).append(r["code"])
        for b in sorted(buckets):
            print(f"{len(buckets[b]):3d}  {b}")
        if a.show and label == "CLEAN KEY":
            for b in sorted(buckets):
                print(b, buckets[b][: a.show])


if __name__ == "__main__":
    main()
