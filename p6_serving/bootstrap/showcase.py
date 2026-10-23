"""The one-off showcase export (p6_serving/notebooks/showcase_export.py): run it, fetch the redacted file, clean up.

  python p6_serving/bootstrap/showcase.py run --branch p6-showcase [--dry-run] --env-file .env     # one run on Databricks serverless, from a pushed git branch
  python p6_serving/bootstrap/showcase.py fetch --env-file .env                                   # writes p6_serving/showcase/showcase.json, then the gate's showcase rules
  python p6_serving/bootstrap/showcase.py cleanup --env-file .env                                  # deletes the scratch folder in the landing volume

Runs as the admin (the raw records hold plaintext contributor names that only bronze keeps). The notebook returns counts only; the redacted file is read by the owner before it is
committed. `fetch` brings only the redacted file to the laptop. Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin) or --env-file. Values are never printed."""
import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

REPO = "https://github.com/Aayush8392/Packsense"
NOTEBOOK = "p6_serving/notebooks/showcase_export"
SCRATCH = "/Volumes/workspace/packsense/landing/_showcase"
OUT = Path(__file__).resolve().parents[1] / "showcase" / "showcase.json"
ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def client():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")


def run(branch: str, dry: bool) -> int:
    from databricks.sdk.service import jobs
    w = client()
    params = {"dry_run": "true" if dry else "false"}
    waiter = w.jobs.submit(
        run_name="packsense-showcase-export", timeout_seconds=1800,
        git_source=jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=branch),
        tasks=[jobs.SubmitTask(task_key="export", disable_auto_optimization=True,
                               notebook_task=jobs.NotebookTask(notebook_path=NOTEBOOK, source=jobs.Source.GIT, base_parameters=params))])
    print("submitted run", waiter.run_id, flush=True)
    try:
        r = waiter.result(timeout=timedelta(minutes=29))
    except Exception as exc:
        r = w.jobs.get_run(waiter.run_id)
        print("run did not succeed:", type(exc).__name__)
    task = r.tasks[0]
    state = task.state.result_state.value if task.state.result_state else task.state.life_cycle_state.value
    print("state:", state)
    out = w.jobs.get_run_output(run_id=task.run_id)
    if out.notebook_output and out.notebook_output.result:
        print("output:", out.notebook_output.result)
    if out.error:
        print("error:", str(out.error)[:1500])
    return 0 if state == "SUCCESS" else 1


def fetch() -> int:
    w = client()
    data = w.files.download(f"{SCRATCH}/showcase.json").contents.read()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {OUT} ({len(data)} bytes)")
    sys.path.insert(0, str(ROOT / "p5_governance"))
    sys.path.insert(0, str(ROOT / "p2_lakehouse"))
    import licence_gate
    bad = licence_gate.check_showcase(OUT)
    print("\n".join(f"VIOLATION {b}" for b in bad) if bad else "OK: the showcase passes the licence gate")
    return 1 if bad else 0


def cleanup() -> int:
    w = client()
    try:
        w.files.delete(f"{SCRATCH}/showcase.json")
    except Exception as e:
        print("no file to delete:", type(e).__name__)
    try:
        w.files.delete_directory(SCRATCH)
        print("scratch folder deleted")
    except Exception as e:
        print("scratch folder not deleted:", type(e).__name__)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "fetch", "cleanup"])
    ap.add_argument("--env-file")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.cmd == "run":
        return run(args.branch, args.dry_run)
    return fetch() if args.cmd == "fetch" else cleanup()


if __name__ == "__main__":
    sys.exit(main())
