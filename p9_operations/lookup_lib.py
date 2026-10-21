"""The daily Databricks lookup of the deletion reconciliation (roadmap item 8; the full-automation aim, context file A67).

The weekly candidate job (notebooks/reconcile_candidates.py) lists the products to ask OFF about. This job asks about the next few hundred of them each day, one at a
time, and appends the answers to `silver_existence_check`. It is the same logic as the Airflow DAG (airflow/reconcile_dag_lib.py: `lookup_one` with its retries and backoff),
without the laptop. Everything here is plain Python so it can be tested with a fake network and a fake clock; the notebook only wires in Spark.

What was measured from Databricks (2026-10-21): in a first test OFF answered HTTP 429 to 8 of 100 requests at a 3 s pace; in a second test 0 of 100 (50 at 6 s, 50 at 3 s
through the real retry code, no retry needed). So rate limits there are intermittent. The safeguards are therefore: the retries and backoff of `lookup_one`, a stop after
three rate-limited codes in a row, a time budget, a cap per run, and progress written after every batch.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "airflow"))
import existence_lib as rl  # noqa: E402
import reconcile_dag_lib as dag  # noqa: E402

DEFAULT_CAP = 500                 # codes asked per run: about 28 minutes at 3.3 s each, if nothing is rate limited
DEFAULT_BUDGET_MINUTES = 60       # the run stops, progress saved, when this is used up (500 codes: 28 minutes clean, about 47 with 8% rate limits)
BATCH_SIZE = 50                   # answers are written to the table after every batch, so an interrupted run keeps what it has
STOP_AFTER_RATE_LIMITED = dag.STOP_AFTER_RATE_LIMITED


def select_pending(candidate_codes: list[str], answered: set[str], cap: int = DEFAULT_CAP) -> list[str]:
    """The first `cap` candidates (in list order) that have no API answer newer than the candidate list. `answered` is the set of codes already answered this cycle,
    by this job or by the Airflow second path."""
    out, seen = [], set()
    for code in candidate_codes:
        if code not in answered and code not in seen:
            seen.add(code)
            out.append(code)
            if len(out) >= cap:
                break
    return out


def table_rows(lines: list[dict], run_id: str) -> list[tuple]:
    """Result lines as rows of silver_existence_check: (code, checked_at, status, detail, evidence_source, snapshot_sha, job_run_id). checked_at is a naive UTC datetime."""
    rows = []
    for x in lines:
        when = dt.datetime.strptime(x["checked_at"], "%Y-%m-%dT%H:%M:%SZ")
        rows.append((x["code"], when, x["status"], x["detail"] or "", rl.EVIDENCE_API, None, run_id))
    return rows


def run_lookups(codes: list[str], write_batch, *, get=dag.http_get, sleep=time.sleep, monotonic=time.monotonic,
                now=lambda: dt.datetime.now(dt.timezone.utc), pause: float = rl.API_PAUSE_SECONDS, budget_seconds: float = DEFAULT_BUDGET_MINUTES * 60,
                batch_size: int = BATCH_SIZE, log=print) -> dict:
    """Ask OFF about `codes` one at a time and hand every batch of answers to `write_batch(lines)` (a list of result lines) as soon as it is complete.
    Stops, after writing what it has, when the time budget is used up or STOP_AFTER_RATE_LIMITED codes in a row stayed rate limited after every retry (those codes
    are NOT written: they are asked again the next day). Returns counts for the run summary and the ping."""
    t0 = monotonic()
    pending: list[dict] = []
    asked = answered = unconfirmed = written = limited_in_a_row = batches = 0
    retries = 0
    stop = None
    for code in codes:
        if monotonic() - t0 > budget_seconds:
            stop = "time budget"
            break
        calls = {"n": 0}

        def counting_get(url, _c=calls):
            _c["n"] += 1
            return get(url)

        line, limited = dag.lookup_one(code, get=counting_get, sleep=sleep, now=now)
        asked += 1
        retries += calls["n"] - 1
        if limited:
            limited_in_a_row += 1
            if limited_in_a_row >= STOP_AFTER_RATE_LIMITED:
                stop = f"{limited_in_a_row} codes in a row still rate limited"
                break
            sleep(pause)
            continue
        limited_in_a_row = 0
        pending.append(line)
        if line["status"] == rl.STATUS_UNCONFIRMED:
            unconfirmed += 1
        else:
            answered += 1
        if len(pending) >= batch_size:
            write_batch(pending)
            written += len(pending)
            batches += 1
            log(f"batch {batches}: {written} answers written, {asked} asked, {retries} retries, {monotonic() - t0:.0f} s")
            pending = []
        sleep(pause)
    if pending:
        write_batch(pending)
        written += len(pending)
        batches += 1
    return {"planned": len(codes), "asked": asked, "written": written, "answered_clearly": answered, "unconfirmed": unconfirmed, "retries": retries,
            "batches": batches, "stopped": stop, "seconds": round(monotonic() - t0)}
