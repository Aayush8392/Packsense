"""Item 15, steps 4d and 5: write stories from code-computed facts with one model, check them with code, judge them with a second model. Resumable, one call at a time.

    python p8_steward/bootstrap/run_story_trials.py --env-file .env --dry          # 3 stories, to read the token costs and the replies
    python p8_steward/bootstrap/run_story_trials.py --env-file .env --trials       # the 40 trials (36 day-and-scope stories plus 4 repeats of event stories)

Narrator openai/gpt-oss-20b, judge qwen/qwen3.8-27b (neither is used by the Wardence project on Groq). A story gets up to two retries (three attempts), each with the checker's list of problems, when the checker finds any.
A trial passes when the checker passes (after at most one retry) and the judge marks every sentence supported. Every attempt is appended to a JSONL file (prompt facts, raw reply, problems,
tokens), so a stopped run resumes where it stopped. Guards: the run stops at the first HTTP error, and stops before a model passes --token-cap tokens in this run; calls are paced under 8,000
tokens a minute. Only counts, facts and generated text are logged; the key is never printed.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import groq_client as gc  # noqa: E402
import story_check as sc  # noqa: E402
import story_facts as sf  # noqa: E402
import story_lib as sl  # noqa: E402
import story_prompts as sp  # noqa: E402

NARRATOR = "openai/gpt-oss-20b"
JUDGE = "qwen/qwen3.8-27b"
TPM_LIMIT = 8000
TPM_SAFE = 6800
DATA = ROOT / "p8_steward" / "data"
DRY_UNITS = [("2026-10-17", "india"), ("2026-10-16", "all"), ("2026-10-12", "all")]
DEV_UNITS = [("2026-10-17", "india"), ("2026-10-23", "all"), ("2026-10-16", "all"), ("2026-10-06", "all"), ("2026-10-12", "all")]      # the five development stories (version 2)


class Pacer:
    def __init__(self):
        self.log: dict[str, list[tuple[float, int]]] = {}
        self.total: dict[str, int] = {}
        self.estimate = {NARRATOR: 4500, JUDGE: 3500}

    def wait(self, model: str):
        while True:
            now = time.time()
            recent = [(t, n) for t, n in self.log.get(model, []) if now - t < 62]
            self.log[model] = recent
            if sum(n for _, n in recent) + self.estimate[model] <= TPM_SAFE:
                return
            time.sleep(max(1.0, 62 - (now - recent[0][0])))

    def add(self, model: str, tokens: int):
        self.log.setdefault(model, []).append((time.time(), tokens))
        self.total[model] = self.total.get(model, 0) + tokens
        self.estimate[model] = max(self.estimate[model] * 0.6 + tokens * 0.4, tokens)


def units(days: dict) -> list[tuple[str, str]]:
    return [(d, s) for d in sf.story_days(days) for s in ("all", "india")]


def trial_list(days: dict, drift: list[dict], quality: dict) -> list[tuple[str, str, int]]:
    """Every day-and-scope story once, then four repeats of event stories chosen by a fixed hash order (not by how they turned out)."""
    base = [(d, s, 1) for d, s in units(days)]
    eventful = [(d, s) for d, s in units(days) if sf.build_request(days, drift, d, s, quality)["events"]]
    order = sorted(eventful, key=lambda u: hashlib.sha256(f"item15|{u[0]}|{u[1]}".encode()).hexdigest())
    return base + [(d, s, 2) for d, s in order[:4]]


def call(key: str, pacer: Pacer, model: str, messages: list[dict], max_tokens: int, cap: int, log: dict, extra: dict | None = None) -> dict:
    if pacer.total.get(model, 0) + pacer.estimate[model] > cap:
        raise SystemExit(f"stopping before {model} passes the {cap} token cap of this run (used {pacer.total.get(model, 0)})")
    pacer.wait(model)
    t0 = time.time()
    r = gc.chat(key, model, messages, max_tokens=max_tokens, extra=extra)
    pacer.add(model, r["total_tokens"])
    log.setdefault("calls", []).append({"model": model, "seconds": round(time.time() - t0, 1), **{k: r[k] for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens", "finish_reason")}})
    return r


def run_trial(key, pacer, days, drift, quality, day, scope, rep, cap) -> dict:
    request = sf.build_request(days, drift, day, scope, quality)
    rec = {"trial": f"{day}|{scope}|{rep}", "day": day, "scope": scope, "rep": rep, "events": request["events"], "attempts": []}
    messages = sp.narrator_messages(request)
    problems: list[tuple[str, str]] = [("R1", "no reply")]
    story = None
    for attempt in (1, 2, 3):
        r = call(key, pacer, NARRATOR, messages, 3000, cap, rec, {"reasoning_effort": "low"})
        story = sc.parse(r["text"])
        problems = sc.check(story, request)
        rec["attempts"].append({"attempt": attempt, "raw": r["text"], "problems": [list(p) for p in problems]})
        if not problems:
            break
        messages = sp.retry_messages(request, r["text"], problems)
    rec["checker_pass"] = not problems
    rec["checker_codes"] = sorted({c for c, _ in problems})
    rec["judge"] = None
    if not problems:
        jr = call(key, pacer, JUDGE, sp.judge_messages(request, story), 2500, cap, rec)
        verdict = sp.parse_judge(jr["text"])
        rec["judge"] = {"raw": jr["text"], "parsed": verdict}
        rec["judge_pass"] = bool(verdict) and isinstance(verdict.get("verdicts"), list) and all(v.get("supported") is True for v in verdict["verdicts"]) and len(verdict["verdicts"]) == len(story["sentences"])
    else:
        rec["judge_pass"] = False
    rec["pass"] = rec["checker_pass"] and rec["judge_pass"]
    rec["story"] = sc.render(story, request) if story and not problems else None
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env-file")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--trials", action="store_true")
    ap.add_argument("--dev", type=int, default=None, metavar="ROUND", help="run the five development stories as round ROUND (version 2)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--token-cap", type=int, default=185000, help="most tokens one model may use in this run")
    ap.add_argument("--limit", type=int, default=None, help="run at most this many trials (a partial run can be resumed)")
    args = ap.parse_args(argv)
    if [args.dry, args.trials, args.dev is not None].count(True) != 1:
        sys.exit("choose exactly one of --dry, --trials and --dev ROUND")
    days = sl.load_days(DATA / "signal_days.csv")
    drift = sl.drift_events(DATA / "drift_events.csv")
    quality = sf.load_quality(DATA / "quality_days.csv")
    plan = [(d, s, 1) for d, s in (DEV_UNITS if args.dev is not None else DRY_UNITS)] if (args.dry or args.dev is not None) else trial_list(days, drift, quality)
    name = f"dev_round{args.dev}.jsonl" if args.dev is not None else ("dry.jsonl" if args.dry else "trials_v2.jsonl")
    out = Path(args.out or DATA / "trials" / name)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(line)["trial"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()} if out.exists() else set()
    key = gc.read_key(args.env_file)
    pacer = Pacer()
    ran = 0
    for day, scope, rep in plan:
        tid = f"{day}|{scope}|{rep}"
        if tid in done:
            continue
        if args.limit is not None and ran >= args.limit:
            break
        try:
            rec = run_trial(key, pacer, days, drift, quality, day, scope, rep, args.token_cap)
        except gc.GroqError as e:
            print(f"stopped on {tid}: {e}")
            return 1
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ran += 1
        used = sum(c["total_tokens"] for c in rec["calls"])
        print(f"{tid:<28} events {len(rec['events'])}  attempts {len(rec['attempts'])}  checker {'pass' if rec['checker_pass'] else 'FAIL ' + ','.join(rec['checker_codes'])}  judge {rec['judge_pass']}  tokens {used}")
        if args.dry or args.dev is not None:
            print("   story:", rec["story"])
            for a in rec["attempts"]:
                if a["problems"]:
                    print("   attempt", a["attempt"], "problems:", a["problems"][:4])
    all_recs = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"trials logged: {len(all_recs)}; passed {sum(1 for r in all_recs if r['pass'])}; tokens this run {pacer.total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
