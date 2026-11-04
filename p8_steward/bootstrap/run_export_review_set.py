"""Runs the review-set export notebook (p8_steward/notebooks/export_review_set.py) once on Databricks serverless, from a git branch, and prints its result.
A one-off run, not a job. The branch must be pushed first (the run reads it from GitHub).

  python p8_steward/bootstrap/run_export_review_set.py --branch item22-review-store-gateway --env-file .env [--exclude 8901063341500,...]
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin); values are never printed. The admin needs SELECT on the production gold schema and on bronze
(the same as the fixture export). Fetch the result with p8_steward/bootstrap/fetch_review_set.py.
"""
import argparse
import os
import sys
from datetime import timedelta

REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p8_steward/notebooks/export_review_set"
TIMEOUT_SECONDS = 1800


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--exclude", default="", help="barcodes to leave out, comma separated (the sample products)")
    ap.add_argument("--limit-per-group", default="36")
    ap.add_argument("--india-per-group", default="22")
    ap.add_argument("--name", help="a further part of the review set (for example dev2): written to its own volume folder, fetched with fetch_review_set.py --name")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    params = {"run_id": "{{job.run_id}}", "exclude_codes": args.exclude, "limit_per_group": args.limit_per_group, "india_per_group": args.india_per_group}
    if args.name:
        params["out_dir"] = f"/Volumes/workspace/packsense_dev/landing/_review_set_{args.name}"

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    waiter = w.jobs.submit(
        run_name="packsense-export-review-set", timeout_seconds=TIMEOUT_SECONDS,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=args.branch),
        tasks=[jobs.SubmitTask(task_key="export", notebook_task=jobs.NotebookTask(notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters=params))])
    print("submitted run", waiter.run_id, flush=True)
    try:
        run = waiter.result(timeout=timedelta(minutes=29))
    except Exception as exc:        # the run is NOT cancelled here; read its state below
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
