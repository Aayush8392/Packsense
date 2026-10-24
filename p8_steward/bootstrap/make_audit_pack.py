"""Item 15, step 6: the owner's blind reading pack. Writes p8_steward/data/trials/audit_pack.md (no pass or fail marks, A and B in a fixed random order) and audit_key.json (which is which).

    python p8_steward/bootstrap/make_audit_pack.py

Ten stories that passed both the checker and the judge, picked by a fixed hash order, plus every story the judge failed. Each item shows the facts, the model's story and the template story
(same facts, filled in by code) as A and B. The owner marks (1) any claim in either text the facts do not support or that misleads, and (2) which text they would rather read.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import story_check as sc  # noqa: E402
import story_facts as sf  # noqa: E402
import story_lib as sl  # noqa: E402
import story_template as st  # noqa: E402

DATA = ROOT / "p8_steward" / "data"


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def main() -> int:
    days = sl.load_days(DATA / "signal_days.csv")
    drift = sl.drift_events(DATA / "drift_events.csv")
    recs = [json.loads(line) for line in (DATA / "trials" / "trials.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    passed = sorted((r for r in recs if r["pass"] and r["rep"] == 1), key=lambda r: h("audit|" + r["trial"]))[:10]
    judged_failed = [r for r in recs if r["judge"] and not r["judge_pass"]]
    chosen = passed + judged_failed
    chosen.sort(key=lambda r: h("order|" + r["trial"]))
    lines = ["# Reading pack: which story is better, and is anything in them wrong?", "",
             "For each item, read the FACTS, then text A and text B. Both were written from the same facts. Answer two questions per item:",
             "1. Does A or B say anything the facts do not support, or that could mislead a reader? (A, B, both, neither; say which sentence)",
             "2. Which would you rather read? (A or B)", "",
             "The caveats and the 'AI-generated' label that code adds under every story are left out here. Facts show: label, value, the usual level, and the change code computed.", ""]
    key = {}
    for n, r in enumerate(chosen, start=1):
        day, scope = r["day"], r["scope"]
        request = sf.build_request(days, drift, day, scope)
        ai = sc.parse(r["attempts"][-1]["raw"])
        ai_text = " ".join(s["text"] for s in ai["sentences"])
        tpl_text = " ".join(s["text"] for s in st.sentences(request))
        ai_first = int(h("ab|" + r["trial"]), 16) % 2 == 0
        a, b = (ai_text, tpl_text) if ai_first else (tpl_text, ai_text)
        key[str(n)] = {"trial": r["trial"], "A": "model" if ai_first else "template", "B": "template" if ai_first else "model", "judge_failed": r in judged_failed}
        lines += [f"## Item {n}: {request['date_words']} 2026, {'India' if scope == 'india' else 'all markets'}", "", "Facts:"]
        for f in request["facts"]:
            extra = f", {f['times_usual']} times the usual" if "times_usual" in f else ""
            lines.append(f"- {f['label']}: {f['value']} (usual {f['usual']}{extra}); change: {f['direction'].replace('_', ' ')}")
        for p in request["patterns"]:
            lines.append(f"- Named pattern matched by code: {p['pattern'].replace('_', ' ')}; {p.get('must_state', '')}")
        lines += ["", f"**Text A:** {a}", "", f"**Text B:** {b}", "", "Your answers: 1. ______  2. ______", ""]
    (DATA / "trials" / "audit_pack.md").write_text("\n".join(lines), encoding="utf-8")
    (DATA / "trials" / "audit_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"wrote {len(chosen)} items ({len(passed)} random passed stories and {len(judged_failed)} judge-failed) to p8_steward/data/trials/audit_pack.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
