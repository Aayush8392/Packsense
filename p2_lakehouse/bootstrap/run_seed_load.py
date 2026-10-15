"""Runs the India seed notebook (p2_lakehouse/notebooks/seed_dump_load.py) once on Databricks serverless, from a git branch,
and prints its result. It is a one-time job, not a scheduled one, so it is submitted as a one-off run, not created as a job.

  python p2_lakehouse/bootstrap/run_seed_load.py --env-file PATH [--branch main] --param mode=stage [--param name=value ...]
Modes (see the notebook): stage | promote | drop_stage. Other widgets: last_part, stage_schema, bronze_schema, dump_date,
hf_secret_name (the NAME of the secret, never its value), allow_old_contract (tests only).
Secrets are never parameters: the notebook reads the Hugging Face token from the secret scope `packsense`.
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed.
"""
import argparse
import os
import re
import sys
from datetime import timedelta

REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p2_lakehouse/notebooks/seed_dump_load"
# real token shapes (a secret NAME such as hf_dump_read_token has underscores after the prefix and does not match)
LOOKS_LIKE_A_TOKEN = re.compile(r"^(hf_[A-Za-z0-9]{20,}|K00[0-9][A-Za-z0-9+/]{20,}|sk-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,}"
                                r"|github_pat_[A-Za-z0-9_]{20,}|dapi[a-f0-9]{20,})$")


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def check_params(params: dict) -> None:
    for k, v in params.items():
        if LOOKS_LIKE_A_TOKEN.match(v):
            sys.exit(f"parameter {k} looks like a token: secrets are never job parameters")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--param", action="append", default=[])
    args = ap.parse_args()
    load_env_file(args.env_file)
    params = dict(p.split("=", 1) for p in args.param)
    check_params(params)

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service import jobs
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"])
    params.setdefault("run_id", "{{job.run_id}}")
    waiter = w.jobs.submit(
        run_name=f"packsense-seed-{params.get('mode', 'stage')}", timeout_seconds=3300,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=args.branch),
        tasks=[jobs.SubmitTask(task_key="seed", notebook_task=jobs.NotebookTask(
            notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters=params))])
    print("submitted run", waiter.run_id, flush=True)
    try:
        run = waiter.result(timeout=timedelta(minutes=55))
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
