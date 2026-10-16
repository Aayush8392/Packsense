"""Runs the drift notebook (p2_lakehouse/notebooks/drift_check.py) once on Databricks serverless, from a git branch, and prints its result.
It is a one-off run (not a scheduled job): used to verify a change to the drift check against scratch tables before it reaches `main`.

  python p2_lakehouse/bootstrap/run_drift_check.py --env-file PATH [--branch main] --param report_schema=workspace.ps_drift_test [...]
Useful widgets (see the notebook): report_schema (where the report and metrics tables are written; the silver tables are only read),
ping_healthchecks (set to false for tests), evaluate_prefix, baseline_prefix. Secrets are never parameters.
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed.
"""
import argparse
import os
import sys
from datetime import timedelta

REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p2_lakehouse/notebooks/drift_check"


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--param", action="append", default=[])
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    params = dict(p.split("=", 1) for p in args.param)

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"])
    params.setdefault("run_id", "{{job.run_id}}")
    waiter = w.jobs.submit(
        run_name="packsense-drift-check-oneoff", timeout_seconds=3000,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=args.branch),
        tasks=[jobs.SubmitTask(task_key="drift", notebook_task=jobs.NotebookTask(
            notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters=params))])
    print("submitted run", waiter.run_id, flush=True)
    try:
        run = waiter.result(timeout=timedelta(minutes=50))
    except Exception as exc:
        run = w.jobs.get_run(waiter.run_id)
        print("run did not succeed:", type(exc).__name__)
    task = run.tasks[0]
    print("state:", task.state.result_state.value if task.state.result_state else task.state.life_cycle_state.value)
    out = w.jobs.get_run_output(run_id=task.run_id)
    if out.notebook_output and out.notebook_output.result:
        print("output:", out.notebook_output.result)
    if out.error:
        print("error:", str(out.error)[:2000])
    return 0 if task.state.result_state and task.state.result_state.value == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
