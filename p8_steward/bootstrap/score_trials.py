"""Item 15, step 6: score the trial log. Local only, no network.

    python p8_steward/bootstrap/score_trials.py [--log p8_steward/data/trials/trials.jsonl]

Prints the pass counts (all, event days, quiet days, first attempt), the failures with their reasons, the judge's reasons on every judged-failed story, and the tokens used.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default=str(ROOT / "p8_steward" / "data" / "trials" / "trials.jsonl"))
    args = ap.parse_args(argv)
    recs = [json.loads(line) for line in Path(args.log).read_text(encoding="utf-8").splitlines() if line.strip()]
    n = len(recs)
    passed = [r for r in recs if r["pass"]]
    print(f"trials {n}; passed {len(passed)}; failed {n - len(passed)}")
    for label, sel in (("event days", [r for r in recs if r["events"]]), ("quiet days", [r for r in recs if not r["events"]]), ("scope all", [r for r in recs if r["scope"] == "all"]),
                       ("scope india", [r for r in recs if r["scope"] == "india"]), ("repeats", [r for r in recs if r["rep"] == 2])):
        print(f"  {label:<12}{sum(1 for r in sel if r['pass'])} of {len(sel)}")
    first = [r for r in recs if r["attempts"] and not r["attempts"][0]["problems"]]
    print(f"first attempt passed the checker: {len(first)} of {n}; needed the retry: {sum(1 for r in recs if len(r['attempts']) == 2)}; checker failed after the retry: {sum(1 for r in recs if not r['checker_pass'])}")
    judged = [r for r in recs if r["judge"]]
    print(f"judge ran on {len(judged)} stories; marked all supported: {sum(1 for r in judged if r['judge_pass'])}")
    codes: dict[str, int] = {}
    for r in recs:
        for a in r["attempts"]:
            for c, _ in a["problems"]:
                codes[c] = codes.get(c, 0) + 1
    print("checker problems by rule over all attempts:", dict(sorted(codes.items())))
    print("failures:")
    for r in recs:
        if r["pass"]:
            continue
        print(f"  {r['trial']}  events {len(r['events'])}  checker {'pass' if r['checker_pass'] else 'FAIL ' + ','.join(r['checker_codes'])}")
        if not r["checker_pass"]:
            for c, m in r["attempts"][-1]["problems"][:4]:
                print(f"      {c}: {m}")
        elif r["judge"] and r["judge"]["parsed"]:
            for v in r["judge"]["parsed"].get("verdicts", []):
                if v.get("supported") is not True:
                    print(f"      judge, sentence {v.get('n')}: {v.get('reason')}")
    tok = {}
    for r in recs:
        for c in r["calls"]:
            tok[c["model"]] = tok.get(c["model"], 0) + c["total_tokens"]
    print("tokens:", tok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
