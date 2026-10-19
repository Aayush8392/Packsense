"""Start a bundle job (or only some of its tasks) with the ADMIN token and follow it to the end. No principal secret is needed.

  python p3_delivery/bootstrap/run_job.py --match packsense-bronze-load --only drift --env-file .env
  python p3_delivery/bootstrap/run_job.py --match packsense-gold-build --env-file .env
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin), or --env-file PATH. Values are never printed.

A bundle job runs as its owner (a service principal) whoever starts it, so this replaces `bundle run` typed with a principal's secret
(proven on the production gold job 2026-10-18 and on the archive job's reconcile task 2026-10-19). `--match` is a case-insensitive part of the
job name; it must find exactly one job (dev jobs are named like '[dev <user>] packsense-gold-build': check the owner column printed first).
`--only TASK` (repeatable) runs just those tasks. Refuses to start while the job already has an active run. Never cancels a run.
Warning: the bronze job's `capture` task fetches every file OFF still lists into the job's landing volume; on dev use --only with another task.
Exit codes: 0 succeeded, 1 failed or timed out, 2 refused to start.
"""
import argparse
import os
import sys
import time


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def pick_job(jobs: list, needle: str):
    """The one job whose name contains the needle (case-insensitive). Raises LookupError for none or several."""
    hits = [j for j in jobs if needle.lower() in ((j.settings.name if j.settings else "") or "").lower()]
    if len(hits) != 1:
        names = [(j.settings.name if j.settings else None) for j in hits]
        raise LookupError(f"expected exactly one job matching {needle!r}, found {len(hits)}: {names}")
    return hits[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match", required=True)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--env-file")
    ap.add_argument("--timeout-min", type=float, default=25)
    a = ap.parse_args(argv)
    if a.env_file:
        load_env_file(a.env_file)
    for stale in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(stale, None)
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    try:
        job = pick_job(list(w.jobs.list()), a.match)
    except LookupError as e:
        print(e)
        return 2
    print(f"job {job.job_id}: {job.settings.name} (owner/creator: {job.creator_user_name})", flush=True)
    active = list(w.jobs.list_runs(job_id=job.job_id, active_only=True))
    if active:
        print("refusing to start: the job already has an active run", [r.run_id for r in active])
        return 2
    kw = {"only": a.only} if a.only else {}
    run_id = w.jobs.run_now(job_id=job.job_id, **kw).response.run_id
    print("started run", run_id, "only:", a.only or "all tasks", flush=True)
    t0 = time.monotonic()
    while True:
        r = w.jobs.get_run(run_id)
        if r.state.life_cycle_state.value in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            break
        if time.monotonic() - t0 > a.timeout_min * 60:
            print("timed out waiting; the run is NOT cancelled:", run_id)
            return 1
        time.sleep(15)
    print("run:", r.state.life_cycle_state.value, r.state.result_state.value if r.state.result_state else None)
    for t in r.tasks or []:
        print(" ", t.task_key, t.state.life_cycle_state.value, t.state.result_state.value if t.state.result_state else None)
        if t.state.result_state and t.state.result_state.value not in ("SUCCESS", "EXCLUDED"):
            try:
                print("    error:", (w.jobs.get_run_output(t.run_id).error or "")[:600])
            except Exception as e:  # noqa: BLE001
                print("    output unavailable:", type(e).__name__)
    return 0 if r.state.result_state and r.state.result_state.value == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
