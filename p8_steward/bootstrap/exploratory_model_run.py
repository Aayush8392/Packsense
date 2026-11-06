"""EXPLORATORY run of the sealed-test reader with another model (not a sealed result: the model was chosen after the first result was seen).

  python p8_steward/bootstrap/exploratory_model_run.py --model gemini-3.5-flash-lite [--limit N] [--part test] [--version v3rows]

The method is the frozen one: the same prompt, scan text, guards and decision code (dev_ocr_reader, reader_decision, answer_key_lib, scan_layout, rule_evidence are imported, never changed).
Only the model and the endpoint differ. Gemini is reached through Google's OpenAI-compatible endpoint with GEMINI_API_KEY from .env (never printed). Readings go to
output/review_set/dev_ocr_<version>_<part>__<model>.json; the Qwen readings are never touched. Score with: report_sealed_test.py --readings <that file>.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(HERE))
import answer_key_lib as ak  # noqa: E402
import dev_ocr_reader as dr  # noqa: E402
import gateway as gw  # noqa: E402

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
PAUSE = 5                      # seconds between calls (Flash-Lite allows 15 a minute; the pacing does not change the answers)


def readings_path(part: str, version: str, model: str) -> Path:
    return dr.SET / f"dev_ocr_{version}_{part}__{model}.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--part", default="test")
    ap.add_argument("--version", default="v3rows")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many NEW calls (the daily request limit of a model)")
    ap.add_argument("--max-output", type=int, default=700)
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args()
    steward = json.loads((ROOT / "p8_steward" / "gateway_config.json").read_text(encoding="utf-8"))["roles"]["steward"]
    cfg = {"endpoint": ENDPOINT, "budget_share": 1.0,
           "roles": {"steward": {**steward, "model": a.model, "daily_tokens": 10_000_000, "max_output_tokens": a.max_output}}}
    gateway = gw.Gateway(gw.read_key("GEMINI_API_KEY", a.env_file), config=cfg, usage=gw.UsageLog(ROOT / "output" / "gateway_usage_gemini.jsonl"))
    out_file = readings_path(a.part, a.version, a.model)
    done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    new = 0
    for code in dr.usable_cards(a.part, a.version):
        if code in done:
            continue
        if a.limit and new >= a.limit:
            break
        text = dr.scan_text(code, a.version)[:6000]
        if not ak.text_has_table(text):
            done[code] = {"answer": "", "reading": None, "tokens": 0, "skipped": "no readable table in the scan"}
            print(code, "skipped: no readable table in the scan", flush=True)
            continue
        messages = [{"role": "system", "content": dr.SYSTEMS[a.version]}, {"role": "user", "content": f"<ocr>\n{text}\n</ocr>"}]
        try:
            res = gateway.call("steward", messages)
        except gw.GatewayError as e:
            print(code, "STOP", e.kind, str(e)[:500], e.retry_after)
            break
        new += 1
        done[code] = {"answer": res["text"], "reading": dr.read_json(res["text"]), "tokens": res["provenance"]["total_tokens"],
                      "finish": res["finish_reason"], "completion_tokens": res["provenance"]["completion_tokens"]}
        time.sleep(PAUSE)
        second = dr.retry_if_needed(gateway, messages, done[code], text)
        if second:
            done[code] = {**second, "first": {"answer": done[code]["answer"], "reading": done[code]["reading"]}, "tokens": done[code]["tokens"] + second["tokens"]}
            print(code, "retried:", second["why"][:120], flush=True)
        out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(code, "ok", done[code]["tokens"], "tokens", done[code].get("finish"), flush=True)
        time.sleep(PAUSE)
    out_file.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(done)} readings saved ({new} new calls this run); tokens: {sum(v['tokens'] for v in done.values())}")


if __name__ == "__main__":
    main()
