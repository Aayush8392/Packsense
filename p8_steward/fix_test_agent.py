"""Run the (unchanged) pack-text reader on the history-key repair test and score it. DEVELOPMENT slice only until the freeze.

  python p8_steward/fix_test_agent.py run   --model gemini-3.5-flash-lite [--set dev] [--limit N]    one call per product that has a readable table (resumable)
  python p8_steward/fix_test_agent.py score --model gemini-3.5-flash-lite [--set dev]                no model call: decide, classify, compare with the code baseline

The method is the one of the sealed tests, imported and not edited: the model sees ONLY the scan text (never the stored record, never the post-fix values), code drops values not printed
in the text and decides about the PRE-fix stored values (reader_decision.decide, version 'v3rows'). Readings go to output/review_set/fix_test_readings_<set>__<model>.json.
Gemini models use GEMINI_API_KEY, any other model the Groq key of gateway_config.json; keys are read from .env and never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
import dev_ocr_reader as dr  # noqa: E402
import fix_test_lib as t  # noqa: E402
import gateway as gw  # noqa: E402
import history_key_scan_check as hk  # noqa: E402
import reader_decision as rd  # noqa: E402

VERSION = "v3rows"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
PAUSE = 5


def files(which: str, model: str) -> tuple[Path, Path]:
    return hk.REVIEW / f"fix_test_{which}.json", hk.REVIEW / f"fix_test_readings_{which}__{model.replace('/', '_')}.json"


def make_gateway(model: str, env_file: str):
    steward = json.loads((ROOT / "p8_steward" / "gateway_config.json").read_text(encoding="utf-8"))["roles"]["steward"]
    if model.startswith("gemini"):
        cfg = {"endpoint": GEMINI, "budget_share": 1.0, "roles": {"steward": {**steward, "model": model, "daily_tokens": 10_000_000, "max_output_tokens": 700}}}
        return gw.Gateway(gw.read_key("GEMINI_API_KEY", env_file), config=cfg, usage=gw.UsageLog(ROOT / "output" / "gateway_usage_gemini.jsonl"))
    base = gw.load_config()
    cfg = {**base, "roles": {"steward": {**base["roles"]["steward"], "model": model}}}
    return gw.Gateway(gw.read_key("GROQ_API_KEY", env_file), config=cfg)


def sealed_gate() -> None:
    """The FINAL block is run only while the freeze record holds (freeze_fix_test.py check). Rounds 1 and 2 are development rounds and are not gated."""
    import freeze_fix_test as ff
    then = json.loads(ff.OUT.read_text(encoding="utf-8"))["record"]
    now = ff.record()
    broken = sorted(k for k in set(now) | set(then) if now.get(k) != then.get(k))
    if broken:
        sys.exit(f"FREEZE BROKEN: {broken}; the sealed set is not run")


def run(which: str, model: str, limit: int, env_file: str) -> None:
    rows_file, out_file = files(which, model)
    rows = json.loads(rows_file.read_text(encoding="utf8"))
    if which == "final":
        sealed_gate()
    done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    gateway, new = make_gateway(model, env_file), 0
    for row in rows:
        code = row["code"]
        if code in done:
            continue
        if limit and new >= limit:
            break
        if not (hk.REVIEW / "ocr_json" / f"{code}.json").exists():
            print(code, "scan file missing: fetch it first (nothing recorded)")
            continue
        text = dr.scan_text(code, VERSION)[:6000]
        if not akl.text_has_table(text):
            done[code] = {"answer": "", "reading": None, "tokens": 0, "skipped": "no readable table in the scan"}
            continue
        messages = [{"role": "system", "content": dr.SYSTEMS[VERSION]}, {"role": "user", "content": f"<ocr>\n{text}\n</ocr>"}]
        try:
            res = gateway.call("steward", messages)
        except gw.GatewayError as e:
            print(code, "STOP", e.kind, str(e)[:400], e.retry_after)
            break
        new += 1
        done[code] = {"answer": res["text"], "reading": dr.read_json(res["text"]), "tokens": res["provenance"]["total_tokens"], "finish": res["finish_reason"], "model": res["provenance"]["model"]}
        time.sleep(PAUSE)
        second = dr.retry_if_needed(gateway, messages, done[code], text)
        if second:
            done[code] = {**second, "first": {"answer": done[code]["answer"], "reading": done[code]["reading"]}, "tokens": done[code]["tokens"] + second["tokens"], "model": done[code]["model"]}
        out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(code, "ok", done[code]["tokens"], "tokens", flush=True)
        time.sleep(PAUSE)
    out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(done)} readings saved ({new} new calls); tokens {sum(v['tokens'] for v in done.values())}")


def score(which: str, model: str) -> None:
    rows_file, out_file = files(which, model)
    rows = json.loads(rows_file.read_text(encoding="utf8"))
    readings = json.loads(out_file.read_text(encoding="utf-8"))
    agent, agent_fill, hyb_a, hyb_b, hyb_c, code_cls, actions, adjud, by_group = [], [], [], [], [], [], {}, {}, {}
    kept = []
    for row in rows:
        entry = readings.get(row["code"])
        if entry is None:
            continue
        text = dr.scan_text(row["code"], VERSION)[:6000]
        group = t.group_of_row(row)
        decision = rd.decide(t.before(row), entry.get("reading"), text, group, VERSION)
        actions[decision["action"]] = actions.get(decision["action"], 0) + 1
        proposal = t.agent_proposal(decision)
        cls = t.classify(row, proposal)
        agent.append(cls)
        filled = t.complete_partners(t.before(row), decision.get("reading100") or {}, proposal) if proposal else None
        agent_fill.append(t.classify(row, filled))
        hyb_a.append(t.classify(row, t.hybrid_pick(row, decision.get("reading100"))))
        hyb_b.append(t.classify(row, t.hybrid_agent_first(row, filled)))
        hyb_c.append(t.classify(row, t.hybrid_agent_then_reading(row, filled, decision.get("reading100"))))
        code_cls.append(t.classify(row, t.code_proposal(row)))
        kept.append(row)
        by_group.setdefault(group, []).append(cls)
        if cls == "valid_alternative":
            f = hk.REVIEW / "ocr_json" / f"{row['code']}.json"
            side = t.printed_side(row, proposal, hk.scan_text(json.loads(f.read_text(encoding="utf8")))) if f.exists() else "no_scan_file"
            adjud[side] = adjud.get(side, 0) + 1
    print(f"model {model}: {len(kept)} of {len(rows)} products have a reading (the rest are not run); tokens {sum(v['tokens'] for v in readings.values())}")
    clean = [t.clean_key(r) for r in kept]
    for label, mask in (("ALL ELIGIBLE", [True] * len(kept)), ("CLEAN KEY (primary)", clean)):
        ag, af, co, ha, hb, hc = ([c for c, m in zip(xs, mask) if m] for xs in (agent, agent_fill, code_cls, hyb_a, hyb_b, hyb_c))
        print(f"--- {label}: {len(ag)} products")
        print("code            ", json.dumps(t.split(co)))
        print("agent as frozen ", json.dumps(t.split(ag)))
        print("paired vs code  ", json.dumps(t.paired(ag, co)))
        print("agent + partner fill", json.dumps(t.split(af)))
        print("paired vs code  ", json.dumps(t.paired(af, co)))
        print("HYBRID A (reading picks a code candidate)", json.dumps(t.split(ha)))
        print("paired vs code  ", json.dumps(t.paired(ha, co)))
        print("HYBRID B (agent first, code as fallback)", json.dumps(t.split(hb)))
        print("paired vs code  ", json.dumps(t.paired(hb, co)))
        print("HYBRID C (agent first, then the reading picks a code candidate)", json.dumps(t.split(hc)))
        print("paired vs code  ", json.dumps(t.paired(hc, co)))
    print("actions", json.dumps(actions, indent=0))
    print("agent alternatives, which side is printed in the scan:", adjud)
    for g, cs in sorted(by_group.items()):
        print(g, len(cs), {k: cs.count(k) for k in ("agrees", "valid_alternative", "breaks_rule", "abstain")})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--set", default="dev", choices=["dev", "round1", "round2", "final"], dest="which")          # 'final' runs only while the freeze record holds (sealed_gate); the rounds are development
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args()
    run(a.which, a.model, a.limit, a.env_file) if a.cmd == "run" else score(a.which, a.model)


if __name__ == "__main__":
    main()
