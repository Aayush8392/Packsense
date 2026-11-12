"""Runs both readers of round 2 over output/review_set/fix_test_round2.json (214 products), only while the freeze record holds.

  python p8_steward/bootstrap/run_round2_readers.py plan                       counts the calls the run would make; no call, no key read
  python p8_steward/bootstrap/run_round2_readers.py text  [--max-calls N]       the frozen text reader (fix_test_agent.run, set round2); resumable
  python p8_steward/bootstrap/run_round2_readers.py photo [--max-calls N]       the photo reader (photo_method / vision_variant_test.call); resumable

Rules of the run (written before it): the freeze record must hold (freeze_fix_test.py check) or nothing starts; a product whose photo is missing or whose scan text holds no table is NOT sent
to the photo reader (the rule's answer for it is silence anyway); the FIRST error of any kind stops the run, nothing is retried past a quota error; every photo call is logged to
output/review_set/round2_call_log.jsonl (photo calls bypass the gateway's usage log) with the time and the model the response named; --max-calls caps the NEW calls of one run (default 380).
The Gemini day resets at 13:30 India time (08:00 UTC; Pacific midnight): the plan prints how many calls the log shows since the last reset.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
import fix_test_agent as fa  # noqa: E402
import gateway as gw  # noqa: E402
import photo_method as pm  # noqa: E402
import vision_variant_test as vv  # noqa: E402

R = ROOT / "output" / "review_set"
PHOTOS = R / "photos_round2"
CALL_LOG = R / "round2_call_log.jsonl"
PHOTO_READINGS = R / f"fix_test_photo_readings_round2__{pm.MODEL}.json"
DEFAULT_MAX_CALLS = 380
RESET_UTC_HOUR = 8                    # 13:30 India time; Pacific midnight while the US is on standard time (the notes' reset time; confirm on the AI Studio rate-limit page)


def gemini_day_start(now: dt.datetime) -> dt.datetime:
    start = now.replace(hour=RESET_UTC_HOUR, minute=0, second=0, microsecond=0)
    return start if now >= start else start - dt.timedelta(days=1)


def calls_since_reset(log_lines: list[str], now: dt.datetime) -> int:
    start = gemini_day_start(now)
    n = 0
    for line in log_lines:
        if line.strip() and dt.datetime.fromisoformat(json.loads(line)["at"]) >= start:
            n += 1
    return n


def plan(rows: list[dict], text_of, photo_exists, have_scan) -> dict:
    """What the run would do. text_of(code) is the scan text the readers see, photo_exists(code) says whether the resized photo is on disk, have_scan(code) whether the scan file is."""
    out = {"products": len(rows), "scan_missing": 0, "no_table": 0, "text_calls": 0, "no_photo": 0, "photo_calls": 0}
    for r in rows:
        code = r["code"]
        if not have_scan(code):
            out["scan_missing"] += 1
            continue
        if not akl.text_has_table(text_of(code)):
            out["no_table"] += 1
            continue
        out["text_calls"] += 1
        if photo_exists(code):
            out["photo_calls"] += 1
        else:
            out["no_photo"] += 1
    return out


def rows() -> list[dict]:
    return json.loads((R / "fix_test_round2.json").read_text(encoding="utf8"))


def gate() -> None:
    import freeze_fix_test as ff
    if not ff.OUT.exists():
        sys.exit("no freeze record: write it first (freeze_fix_test.py write)")
    then = json.loads(ff.OUT.read_text(encoding="utf-8"))["record"]
    now = ff.record()
    broken = sorted(k for k in set(now) | set(then) if now.get(k) != then.get(k))
    if broken:
        sys.exit(f"FREEZE BROKEN: {broken}; nothing runs")


def cmd_plan() -> None:
    p = plan(rows(), pm.ocr_text, lambda c: (PHOTOS / f"{c}.jpg").exists(), lambda c: (R / "ocr_json" / f"{c}.json").exists())
    done_text = R / f"fix_test_readings_round2__{pm.MODEL}.json"
    done_photo = json.loads(PHOTO_READINGS.read_text(encoding="utf-8")) if PHOTO_READINGS.exists() else {}
    log = CALL_LOG.read_text(encoding="utf-8").splitlines() if CALL_LOG.exists() else []
    now = dt.datetime.now(dt.timezone.utc)
    print(json.dumps(p), "| text readings on disk:", len(json.loads(done_text.read_text(encoding="utf-8"))) if done_text.exists() else 0, "| photo readings on disk:", len(done_photo))
    print(f"photo calls logged since the last Gemini reset ({gemini_day_start(now):%Y-%m-%d %H:%M} UTC): {calls_since_reset(log, now)}; text calls are in output/gateway_usage_gemini.jsonl")
    print("a run needs about", p["text_calls"] + p["photo_calls"], "calls in all; the limit is 500 a day (confirm what is left on the AI Studio rate-limit page)")


def cmd_text(max_calls: int, env_file: str) -> None:
    gate()
    fa.run("round2", pm.MODEL, max_calls, env_file)


def cmd_photo(max_calls: int, env_file: str) -> None:
    gate()
    key = gw.read_key("GEMINI_API_KEY", env_file)
    done = json.loads(PHOTO_READINGS.read_text(encoding="utf-8")) if PHOTO_READINGS.exists() else {}
    new = 0
    for row in rows():
        code = row["code"]
        photo = PHOTOS / f"{code}.jpg"
        if code in done or not photo.exists() or not (R / "ocr_json" / f"{code}.json").exists() or not akl.text_has_table(pm.ocr_text(code)):
            continue
        if new >= max_calls:
            print(f"--max-calls {max_calls} reached")
            break
        try:
            r = vv.call(key, photo)
        except gw.GatewayError as e:
            print(code, "STOP", e.kind, str(e)[:300], e.retry_after)
            break
        with CALL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(), "kind": "photo", "code": code, "tokens": r["tokens"], "model": r["model"]}) + "\n")
        new += 1
        r["reading"] = vv.dr.read_json(r["answer"])
        if r["reading"] is None:                                         # one retry for unusable JSON, as the text reader does
            time.sleep(vv.PAUSE)
            try:
                r2 = vv.call(key, photo)
            except gw.GatewayError as e:
                print(code, "STOP (retry)", e.kind, str(e)[:300], e.retry_after)
                done[code] = r
                break
            with CALL_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(), "kind": "photo-retry", "code": code, "tokens": r2["tokens"], "model": r2["model"]}) + "\n")
            new += 1
            r2["reading"], r2["tokens"] = vv.dr.read_json(r2["answer"]), r["tokens"] + r2["tokens"]
            r = r2
        done[code] = r
        PHOTO_READINGS.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(code, "ok", r["tokens"], "tokens", r.get("finish"), r.get("model"), flush=True)
        time.sleep(vv.PAUSE)
    PHOTO_READINGS.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(done)} photo readings saved ({new} new calls); tokens {sum(v['tokens'] for v in done.values())}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "text", "photo"])
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    a = ap.parse_args()
    {"plan": lambda: cmd_plan(), "text": lambda: cmd_text(a.max_calls, a.env_file), "photo": lambda: cmd_photo(a.max_calls, a.env_file)}[a.cmd]()


if __name__ == "__main__":
    main()
