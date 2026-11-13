"""Entry point of the nightly photo-reading job (A121 settled 2026-11-13). Prints COUNTS ONLY: the repository is public, so its Actions logs are public.

  python p8_steward/nightly/run_nightly.py --mode fetch-only [--limit 30]      stage 0: the OFF fetch for the first N candidates, no model call, nothing written
  python p8_steward/nightly/run_nightly.py --mode scratch [--max-calls 60]     stage 1: a full night against the SCRATCH dataset (HF_NIGHTLY_SCRATCH_REPO)
  python p8_steward/nightly/run_nightly.py --mode real                         a night against the real results dataset (HF_NIGHTLY_REPO)

Environment (names only; values live in GitHub secrets and variables): HF_NIGHTLY_WRITE_TOKEN, HF_NIGHTLY_REPO, HF_NIGHTLY_SCRATCH_REPO, GEMINI_API_KEY (not needed for fetch-only).
Exit code: 0 = the night ran (it may have ended at the call ceiling, which is the normal end of a busy night); 1 = it stopped for a reason that must turn the run red (freeze broken, canary failed,
wrong model, a run of 503s, OFF not answering, the time limit, too few lines for the products read) or a fetch failed in fetch-only; 2 = the input or the setup is wrong (a missing, invalid or stale input
file, a missing variable); 3 = the night's results could not be saved after retries. A red night still writes its run record. Progress is saved every 50 settled products, so a crash loses at most that many.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
from nightly import budget as bd  # noqa: E402
from nightly import freeze_nightly as fz  # noqa: E402
from nightly import night as nt  # noqa: E402
from nightly import queue_lib as ql  # noqa: E402
from nightly import store as st  # noqa: E402

RED_STOPS = {"freeze_broken", "canary_failed", "model_mismatch", "503_streak", "time_limit", "off_unavailable", "low_yield"}      # call_ceiling is a normal end
MAX_EXPORT_AGE_DAYS = 2        # a real night refuses a candidates export older than this
MODES = ("fetch-only", "scratch", "real")


def _hf_backend(repo: str, token: str):
    return st.HfBackend(repo, token)


def _default_readers(env: dict, need_model: bool):
    try:
        from nightly import readers
    except ImportError as e:                                       # the real readers are step 3b
        raise SystemExit("the real readers (nightly/readers.py) are not built yet") from e
    return readers.make_readers(env, need_model=need_model)


def fetch_only(candidates: list[dict], readers, limit: int, out) -> int:
    """Stage 0: the OFF fetch alone, for the first `limit` candidates in the queue's fixed order. Counts and timings only."""
    codes = {c["code"]: c for c in candidates}
    picked = sorted(codes, key=ql.order_key)[:limit]
    secs, errors, photo, table = [], {}, 0, 0
    for code in picked:
        t0 = time.monotonic()
        try:
            got = readers.fetch(code)
        except Exception as e:                                     # every failure kind is counted, never printed with a product
            errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
            secs.append(time.monotonic() - t0)
            continue
        secs.append(time.monotonic() - t0)
        photo += bool(got.get("has_photo"))
        table += bool(akl.text_has_table(got.get("ocr_text") or ""))
    n = len(picked)
    out(f"fetch-only: {n} products, {n - sum(errors.values())} fetched, errors {errors or 'none'}, with a photo {photo}, with a table in the scan {table}, "
        f"seconds per product min {min(secs, default=0):.1f} mean {sum(secs) / max(len(secs), 1):.1f} max {max(secs, default=0):.1f}, total {sum(secs):.0f}")
    return 1 if errors else 0


def run(mode: str, env: dict, night: str, limit: int = 30, max_calls: int = bd.MAX_CALLS, backend_factory=_hf_backend, readers_factory=_default_readers,
        freeze_problems=fz.problems, budget_factory=bd.Budget, out=print) -> int:
    repo_var = "HF_NIGHTLY_SCRATCH_REPO" if mode == "scratch" else "HF_NIGHTLY_REPO"
    missing = [v for v in (repo_var, "HF_NIGHTLY_WRITE_TOKEN") + (() if mode == "fetch-only" else ("GEMINI_API_KEY",)) if not env.get(v)]
    if missing:
        out(f"setup error: missing {', '.join(missing)}")
        return 2
    store = st.Store(backend_factory(env[repo_var], env["HF_NIGHTLY_WRITE_TOKEN"]))
    try:
        candidates = store.load_candidates(night, MAX_EXPORT_AGE_DAYS if mode == "real" else None)
        if mode == "fetch-only":
            return fetch_only(candidates, readers_factory(env, False), limit, out)
        canary, state = store.load_canary(), store.load_state()
    except st.StoreError as e:
        out(f"input error: {e}")
        return 2
    saves = {"checkpoints": 0, "checkpoint_failures": 0}

    def checkpoint(partial: dict) -> None:                        # a failed checkpoint is counted and the night goes on; the final save decides the exit code
        try:
            store.save_night(night, state, {**partial, "invalid_candidates": store.invalid, "partial": True})
            saves["checkpoints"] += 1
        except st.StoreError:
            saves["checkpoint_failures"] += 1

    summary = nt.run_night(state, candidates, readers_factory(env, True), budget_factory(max_calls=max_calls), night, canary, freeze_problems=freeze_problems, checkpoint=checkpoint)
    summary["invalid_candidates"] = summary.get("invalid_candidates", 0) + store.invalid
    summary.update(saves)
    try:
        store.save_night(night, state, summary)
    except st.StoreError as e:
        out(f"save error: {e}; this night's {len(summary['lines'])} lines and queue changes are lost (checkpoints saved {saves['checkpoints']}, failed {saves['checkpoint_failures']})")
        return 3
    c = summary.get("canary") or {}
    out(f"night {night} ({mode}): stopped {summary['stopped']}, calls {summary.get('calls', 0)}, products {summary['products']}, lines {len(summary['lines'])}, "
        f"silences {summary['silences'] or 'none'}, errors {summary['errors'] or 'none'}, canary {c.get('agreed', '-')}/{c.get('total', '-')}, invalid candidates {summary['invalid_candidates']}, "
        f"checkpoints {saves['checkpoints']} (failed {saves['checkpoint_failures']}), queue {summary.get('queue')}")
    return 1 if summary["stopped"] in RED_STOPS else 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--max-calls", type=int, default=bd.MAX_CALLS)
    ap.add_argument("--night", default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"))
    a = ap.parse_args(argv)
    sys.exit(run(a.mode, dict(os.environ), a.night, a.limit, a.max_calls))


if __name__ == "__main__":
    main()
