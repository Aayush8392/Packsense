"""Creates the Databricks job that archives the B2 capture bucket to the private Hugging Face repo.

Two tasks, sourced from this public repo's main branch on serverless compute, one run at a time:
  archive    p1_intake/notebooks/archive_to_hf.py
  retention  p1_intake/notebooks/landing_retention.py   (only if archive succeeded; deletes old landed delta files that bronze and
                                                         the archive both hold; same secrets, no new ones)
It runs as the admin user (a job cannot be bound to a service principal on Free Edition). The secrets it needs are in
the Databricks secret scope `packsense` (names only here): b2_read_key_id, b2_read_application_key, hf_archive_token,
healthchecks_archive_ping_url. They are never job parameters.
This is later brought under Terraform / Asset Bundles; until then it documents exactly what exists.

Needs an admin token in the environment (or in an --env-file). Values are never printed.
  python p1_intake/bootstrap/create_archive_job.py create    [--env-file PATH]   create or update the job (no schedule yet)
  python p1_intake/bootstrap/create_archive_job.py run       [--env-file PATH] [--param name=value ...]   run it once and print the result
  python p1_intake/bootstrap/create_archive_job.py schedule  [--env-file PATH]   attach the daily schedule
  python p1_intake/bootstrap/create_archive_job.py status    [--env-file PATH]   recent runs
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin)
"""
import argparse
import os
import sys
from datetime import timedelta

JOB = "packsense-archive"
REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p1_intake/notebooks/archive_to_hf"
RETENTION_NOTEBOOK = "p1_intake/notebooks/landing_retention"
# 16:00 UTC = 21:30 IST: after the capture (07:30 UTC plus GitHub's observed lateness of up to ~5.5 h) and the 09:00 UTC core run.
# The job back-fills everything not yet archived, so a late capture only means the file is archived the next day.
CRON = "0 0 16 * * ?"


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
        tasks=[jobs.Task(task_key="archive", notebook_task=jobs.NotebookTask(
                   notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters={"run_id": "{{job.run_id}}"})),
               # only if the archive succeeded (the default run_if): an archive problem stops every deletion
               jobs.Task(task_key="retention", depends_on=[jobs.TaskDependency(task_key="archive")], run_if=jobs.RunIf.ALL_SUCCESS,
                         notebook_task=jobs.NotebookTask(notebook_path=RETENTION_NOTEBOOK, source=jobs.Source.GIT,
                                                         base_parameters={"run_id": "{{job.run_id}}"}))],
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
    ap.add_argument("--param", action="append", default=[], help="run: a notebook widget as name=value (tests use scratch values)")
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
        params = dict(p.split("=", 1) for p in args.param)
        if params and any("secret" in k or "token" in k or "key" in k for k in params):
            sys.exit("secrets are never job parameters")
        run = w.jobs.run_now(job_id=job.job_id, notebook_params=params or None).result(timeout=timedelta(minutes=50))
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
