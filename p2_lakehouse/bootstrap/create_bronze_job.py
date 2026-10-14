"""Creates the bronze schema and the Databricks job that loads landed delta files into bronze.

The job runs p2_lakehouse/notebooks/bronze_load.py, sourced from this public repo's main branch, on serverless compute,
one run at a time. It runs as the admin user (a job cannot be bound to a service principal on Free Edition).
This is later brought under Terraform / Asset Bundles; until then it documents exactly what exists.

Needs an admin token in the environment (or in an --env-file). Values are never printed.
  python p2_lakehouse/bootstrap/create_bronze_job.py create    [--env-file PATH]   schema + job (no schedule yet)
  python p2_lakehouse/bootstrap/create_bronze_job.py run       [--env-file PATH]   run it once and print the result
  python p2_lakehouse/bootstrap/create_bronze_job.py schedule  [--env-file PATH]   attach the daily schedule
  python p2_lakehouse/bootstrap/create_bronze_job.py status    [--env-file PATH]   recent runs
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin)
"""
import argparse
import os
import sys
from datetime import timedelta

JOB = "packsense-bronze-load"
REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p2_lakehouse/notebooks/bronze_load"
SCHEMA = "workspace.packsense_bronze"
CRON = "0 0 9 * * ?"  # 09:00 UTC = 14:30 IST, before the 15:00 IST data-ready target


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def settings(with_schedule: bool) -> dict:
    from databricks.sdk.service import jobs
    s = dict(
        name=JOB,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch="main"),
        tasks=[jobs.Task(task_key="bronze", notebook_task=jobs.NotebookTask(
            notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters={"run_id": "{{job.run_id}}"}))],
        max_concurrent_runs=1,
        timeout_seconds=3600,
    )
    if with_schedule:
        s["schedule"] = jobs.CronSchedule(quartz_cron_expression=CRON, timezone_id="UTC", pause_status=jobs.PauseStatus.UNPAUSED)
    return s


def find_job(w):
    return next(iter(w.jobs.list(name=JOB)), None)


def show_run(w, run_id) -> None:
    run = w.jobs.get_run(run_id)
    state = run.state.result_state.value if run.state.result_state else run.state.life_cycle_state.value
    print(f"run {run_id}: {state} | trigger={run.trigger.value if run.trigger else None} | start={run.start_time}")
    for t in run.tasks or []:
        r = t.state.result_state.value if t.state and t.state.result_state else (t.state.life_cycle_state.value if t.state else None)
        print(f"   task {t.task_key}: {r} ({(t.execution_duration or 0) / 1000:.0f}s)")
        out = w.jobs.get_run_output(run_id=t.run_id)
        if out.notebook_output and out.notebook_output.result:
            print("   notebook output:", out.notebook_output.result)
        if out.error:
            print("   error:", str(out.error)[:1500])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create", "run", "schedule", "status"])
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"])
    job = find_job(w)

    if args.command == "create":
        catalog, schema = SCHEMA.split(".")
        try:
            w.schemas.create(name=schema, catalog_name=catalog, comment="PackSense bronze layer (raw, append-only)")
            print(f"created schema {SCHEMA}")
        except Exception as exc:  # already exists
            if "already exists" not in str(exc).lower():
                raise
            print(f"schema {SCHEMA} already exists")
        if job is None:
            print("job created:", w.jobs.create(**settings(False)).job_id)
        else:
            new = settings(False)
            current = w.jobs.get(job_id=job.job_id).settings
            if current.schedule is not None:  # a reset replaces every setting, so carry the schedule over (and its pause state)
                new["schedule"] = current.schedule
            w.jobs.reset(job_id=job.job_id, new_settings=jobs.JobSettings(**new))
            print("job updated:", job.job_id, "(schedule kept)" if current.schedule is not None else "(no schedule)")
    elif job is None:
        sys.exit("job does not exist yet: run the create command first")
    elif args.command == "run":
        run = w.jobs.run_now(job_id=job.job_id).result(timeout=timedelta(minutes=30))
        show_run(w, run.run_id)
    elif args.command == "schedule":
        w.jobs.reset(job_id=job.job_id, new_settings=jobs.JobSettings(**settings(True)))
        print(f"schedule attached: {CRON} (UTC); job id {job.job_id}")
    elif args.command == "status":
        for r in list(w.jobs.list_runs(job_id=job.job_id, limit=8)):
            show_run(w, r.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
