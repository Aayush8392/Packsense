"""Item 15 (version 2): the owner's reading pack for the five development stories. Writes p8_steward/data/trials/dev_pack.md and dev_key.json (which text is which).

    python p8_steward/bootstrap/make_dev_pack.py

For each of the five development days it shows what code computed (the facts that moved and every derived fact) and two texts written from the same facts: the model's and the
template's, as A and B in a fixed random order. The model text is the one from development round 5 (the last full round) when it still passes the current checker; otherwise the
latest earlier round whose story does. No new model call is made.
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
UNITS = [("2026-10-17", "india"), ("2026-10-23", "all"), ("2026-10-16", "all"), ("2026-10-06", "all"), ("2026-10-12", "all")]


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def main() -> int:
    days = sl.load_days(DATA / "signal_days.csv")
    drift = sl.drift_events(DATA / "drift_events.csv")
    quality = sf.load_quality(DATA / "quality_days.csv")
    rounds = {n: {json.loads(line)["trial"]: json.loads(line) for line in (DATA / "trials" / f"dev_round{n}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
              for n in range(1, 7) if (DATA / "trials" / f"dev_round{n}.jsonl").exists()}
    lines = ["# Reading pack, version 2: which note would you rather read?", "",
             "Each item shows what code computed for the day (only the facts that moved, and every derived fact), then two notes written from those same facts. One was written by the model, one by a",
             "template; the order is random and nothing marks which is which. The caveats and the 'AI-generated' label that code adds under every note are left out.", "",
             "For each item: (1) which note would you rather read, A or B? (2) does either say anything that looks wrong or that you cannot follow? (3) is it the kind of conclusion you wanted, yes / partly / no?", ""]
    key = {}
    for n, (day, scope) in enumerate(UNITS, start=1):
        request = sf.build_request(days, drift, day, scope, quality)
        tid = f"{day}|{scope}|1"
        chosen = None
        for rn in (5, 4, 3, 2):
            rec = rounds.get(rn, {}).get(tid)
            if rec and rec["attempts"]:
                story = sc.parse(rec["attempts"][-1]["raw"])
                if not sc.check(story, request):
                    chosen = (rn, story)
                    break
        if not chosen:
            continue
        model_text = " ".join(s["text"] for s in chosen[1]["sentences"])
        template_text = " ".join(s["text"] for s in st.sentences(request))
        model_first = int(h("devpack|" + tid), 16) % 2 == 0
        a, b = (model_text, template_text) if model_first else (template_text, model_text)
        key[str(n)] = {"trial": tid, "A": "model" if model_first else "template", "B": "template" if model_first else "model", "model_round": chosen[0]}
        lines += [f"## Item {n}: {request['date_words']} 2026, {'India' if scope == 'india' else 'all markets'}", "", "What code computed:"]
        for f in request["facts"]:
            if f["direction"] != "usual":
                lines.append(f"- {f['label']}: {f['value']} (usual {f['usual']}); {f['direction'].replace('_', ' ')}")
        for d in request["derived"]:
            if d["derived"] != "steady_summary":
                lines.append(f"- {d['statement']}" + (f"  [conclusion: {d['conclusion_wording']}]" if d.get("conclusion_wording") else ""))
        for p in request["patterns"]:
            lines.append(f"- Pattern matched: {p['statement']}")
        lines += ["", f"**Note A:** {a}", "", f"**Note B:** {b}", "", "Your answers: 1. ______  2. ______  3. ______", ""]
    (DATA / "trials" / "dev_pack.md").write_text("\n".join(lines), encoding="utf-8")
    (DATA / "trials" / "dev_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"wrote {len(key)} items; model rounds used: {sorted({v['model_round'] for v in key.values()})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
