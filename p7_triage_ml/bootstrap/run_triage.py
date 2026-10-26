"""Runs the triage notebook (p7_triage_ml/notebooks/triage_run.py) once on Databricks serverless, from a pushed git branch, and prints its result.
A one-off run, not a job. Modes (widget `mode`): smoke, dev, freeze, final; see the notebook header.

  python p7_triage_ml/bootstrap/run_triage.py --env-file .env --branch main --param mode=smoke --param steps=1 --param from_date=2026-10-11
  python p7_triage_ml/bootstrap/run_triage.py --env-file .env --param mode=final --param steps=4 --param freeze_hash=<hash printed by freeze>
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin), or --env-file PATH. Values are never printed. Only counts and precision figures come back.
"""
import argparse
import os
import sys
from datetime import timedelta

REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p7_triage_ml/notebooks/triage_run"


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
    ap.add_argument("--param", action="append", default=[], help="notebook widget, name=value")
    ap.add_argument("--timeout-min", type=int, default=90)
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    params = dict(p.split("=", 1) for p in args.param)
    params.setdefault("run_id", "{{job.run_id}}")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    waiter = w.jobs.submit(
        run_name=f"packsense-triage-{params.get('mode', 'smoke')}", timeout_seconds=args.timeout_min * 60,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=args.branch),
        tasks=[jobs.SubmitTask(task_key="triage", notebook_task=jobs.NotebookTask(notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters=params))])
    print("submitted run", waiter.run_id, flush=True)
    try:
        run = waiter.result(timeout=timedelta(minutes=args.timeout_min))
    except Exception as exc:
        run = w.jobs.get_run(waiter.run_id)
        print("run did not succeed:", type(exc).__name__)
    task = run.tasks[0]
    print("state:", task.state.result_state.value if task.state.result_state else task.state.life_cycle_state.value)
    out = w.jobs.get_run_output(run_id=task.run_id)
    if out.notebook_output and out.notebook_output.result:
        print("output:", out.notebook_output.result)
    if out.error:
        print("error:", str(out.error)[:2500])
    return 0 if task.state.result_state and task.state.result_state.value == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
