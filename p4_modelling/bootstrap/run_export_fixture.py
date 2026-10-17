"""Runs the fixture export notebook (p4_modelling/notebooks/export_fixture.py) once on Databricks serverless, from a git branch,
and prints its result. A one-off run, not a job. The branch must be pushed first (the run reads it from GitHub).

  python p4_modelling/bootstrap/run_export_fixture.py --branch p4-duckdb
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin), set in your own shell; or pass --env-file PATH. Values are never printed.
The admin needs SELECT on the production gold schema (staging view, product_history, product_flag_spans) and on bronze.
Then fetch the result with p4_modelling/bootstrap/fetch_fixture.py.
"""
import argparse
import os
import sys
from datetime import timedelta

REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p4_modelling/notebooks/export_fixture"


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
    ap.add_argument("--param", action="append", default=[], help="notebook widget, name=value (gold_schema, bronze_table, out_dir)")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    params = dict(p.split("=", 1) for p in args.param)
    params.setdefault("run_id", "{{job.run_id}}")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    waiter = w.jobs.submit(
        run_name="packsense-export-fixture", timeout_seconds=1800,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=args.branch),
        tasks=[jobs.SubmitTask(task_key="export", notebook_task=jobs.NotebookTask(
            notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters=params))])
    print("submitted run", waiter.run_id, flush=True)
    try:
        run = waiter.result(timeout=timedelta(minutes=29))
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
