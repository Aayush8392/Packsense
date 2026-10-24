"""Item 15 (version 3): the owner's reading pack for the code-planned story. Writes p8_steward/data/trials/plan_pack.md. No model call, no tokens.

    python p8_steward/bootstrap/make_plan_pack.py

Ten days: the five development days, then five more picked by a fixed hash order from the days that were not used for development (so the wording is not only shown on the days it was shaped on).
Each item shows what code computed and the note code wrote from it.
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import story_check as sc  # noqa: E402
import story_facts as sf  # noqa: E402
import story_lib as sl  # noqa: E402
import story_plan as sp  # noqa: E402

DATA = ROOT / "p8_steward" / "data"
DEV = [("2026-10-17", "india"), ("2026-10-23", "all"), ("2026-10-12", "all"), ("2026-10-06", "all"), ("2026-10-16", "all")]


def main() -> int:
    days = sl.load_days(DATA / "signal_days.csv")
    drift = sl.drift_events(DATA / "drift_events.csv")
    quality = sf.load_quality(DATA / "quality_days.csv")
    others = sorted(((d, s) for d in sf.story_days(days) for s in ("all", "india") if (d, s) not in DEV), key=lambda u: hashlib.sha256(f"plan|{u[0]}|{u[1]}".encode()).hexdigest())[:5]
    lines = ["# Reading pack, version 3: the note written by code", "",
             "Each item shows what code computed for the day and the note code wrote from it. No model wrote anything. The caveats and the 'AI-generated' label are left out here (and a code-written note",
             "would carry a different label). Items 1 to 5 are the days the wording was shaped on; items 6 to 10 were picked by a fixed hash order from the other days.", "",
             "For each item: (1) is it easy to follow, yes / partly / no? (2) does anything look wrong or unclear (say which sentence)? (3) does it draw the conclusion the data allows, yes / partly / no?", ""]
    for n, (day, scope) in enumerate(DEV + others, start=1):
        r = sf.build_request(days, drift, day, scope, quality)
        ss = sp.plan(r)
        problems = sc.check({"sentences": ss}, r)
        lines += [f"## Item {n}: {r['date_words']} 2026, {'India' if scope == 'india' else 'all markets'}" + ("" if n <= 5 else "  (not a development day)"), "", "What code computed:"]
        for f in r["facts"]:
            if f["direction"] != "usual":
                lines.append(f"- {f['label']}: {f['value']} (usual {f['usual']}); {f['direction'].replace('_', ' ')}")
        for d in r["derived"]:
            if d["derived"] != "steady_summary":
                lines.append(f"- {d['statement']}" + (f"  [conclusion: {d['conclusion_wording']}]" if d.get("conclusion_wording") else ""))
        for p in r["patterns"]:
            lines.append(f"- Pattern matched: {p['statement']}")
        lines += ["", f"**Note:** {' '.join(x['text'] for x in ss)}", "", f"(checker: {'passes every rule' if not problems else problems})", "", "Your answers: 1. ______  2. ______  3. ______", ""]
    (DATA / "trials" / "plan_pack.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote 10 items; others:", others)
    return 0


if __name__ == "__main__":
    sys.exit(main())
