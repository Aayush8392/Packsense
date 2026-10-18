"""Starts the production gold build (job `packsense-gold-build`) with the admin token and follows it to the end.

  python p4_modelling/bootstrap/run_gold_prod.py [--env-file .env] [--job-name packsense-gold-build] [--timeout-min 25]
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin), set in your own shell; or pass --env-file PATH. Values are never printed.

Why this works without the gold principal's secret: a bundle job runs as its owner (`packsense-gold`) whoever starts it; a run started
by the admin records the principal as its creator (checked 2026-10-18, run 580735387546416). Use it AFTER the `deploy-gold` prod
deploy has finished (otherwise the old notebook runs). It runs the same full rebuild as the 09:30 UTC schedule and pings the
`packsense-gold` healthchecks check like any run. Refuses to start when the job is already running or the name is not unique.
Exit codes: 0 build succeeded, 1 build failed or timed out, 2 refused to start.
"""
import argparse
import os
import sys
import time

POLL_SECONDS = 15


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def find_job_id(w, name: str) -> int:
    """The id of the one job with this exact name. Raises LookupError when there is none or more than one."""
    ids = [j.job_id for j in w.jobs.list(name=name) if j.settings is None or j.settings.name == name]
    if len(ids) != 1:
        raise LookupError(f"expected exactly one job named {name!r}, found {len(ids)}")
    return ids[0]


def active_run_ids(w, job_id: int) -> list[int]:
    return [r.run_id for r in w.jobs.list_runs(job_id=job_id, active_only=True)]


def wait_for(w, run_id: int, timeout_s: float, poll_s: float = POLL_SECONDS, sleep=time.sleep, clock=time.monotonic):
    """Poll the run until it reaches a terminal state or the timeout passes; returns the last run object."""
    deadline = clock() + timeout_s
    while True:
        run = w.jobs.get_run(run_id)
        if run.state.life_cycle_state.value in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            return run
        if clock() >= deadline:
            return run
        sleep(poll_s)


def succeeded(run) -> bool:
    return bool(run.state.result_state and run.state.result_state.value == "SUCCESS")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--job-name", default="packsense-gold-build")
    ap.add_argument("--timeout-min", type=float, default=25)
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)

    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    try:
        job_id = find_job_id(w, args.job_name)
    except LookupError as exc:
        print("refused:", exc)
        return 2
    busy = active_run_ids(w, job_id)
    if busy:
        print(f"refused: the job is already running (run {busy[0]}); a second start would queue behind it")
        return 2

    print(f"starting {args.job_name} (job {job_id}) as {w.current_user.me().user_name}", flush=True)
    run_id = w.jobs.run_now(job_id).response.run_id
    print("run", run_id, flush=True)
    run = wait_for(w, run_id, args.timeout_min * 60)
    state = run.state
    print("state:", state.life_cycle_state.value, state.result_state.value if state.result_state else "", flush=True)
    print("runs as (creator):", run.creator_user_name)
    for task in run.tasks or []:
        out = w.jobs.get_run_output(task.run_id)
        if out.notebook_output and out.notebook_output.result:
            print("result:", out.notebook_output.result)
        if out.error:
            print("error:", str(out.error)[:1000])
    if not succeeded(run) and state.life_cycle_state.value not in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
        print(f"still running after {args.timeout_min:g} min: it was NOT cancelled; look at run {run_id} in the Jobs UI")
    return 0 if succeeded(run) else 1


if __name__ == "__main__":
    sys.exit(main())
