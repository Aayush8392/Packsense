"""Weekly deletion reconciliation on Airflow (P9; the logic is in p9_operations/airflow/reconcile_dag_lib.py, the reasoning in existence_lib.py).

Wait for the candidate list that the Databricks job `packsense-reconcile-candidates` leaves in the landing volume (Tuesdays 07:00 UTC), ask OFF's API about every
candidate (batches of 100, one request at a time through the pool `off_api`, resumable), and upload the answers for the Databricks loader (Thursdays 07:00 UTC).
Needs the pool `off_api` with ONE slot and two environment variables in the stack's env file: PACKSENSE_DBX_HOST and PACKSENSE_PIPELINE_TOKEN (the pipeline
user's token: read and write on the landing volume only). No other credential is used.
"""
import os
import sys
from datetime import datetime, timedelta

from airflow.sdk import PokeReturnValue, dag, get_current_context, task

sys.path.insert(0, "/opt/airflow/p9_operations/airflow")      # the repo's p9_operations folder is mounted read-only (see the compose override)
sys.path.insert(0, "/opt/airflow/p9_operations")
import reconcile_dag_lib as lib  # noqa: E402

RESULT_ROOT = "/opt/airflow/dags/data/reconcile"             # small result files, one per code, kept so an interrupted run resumes
POOL = "off_api"


def landing():
    return lib.Landing(os.environ["PACKSENSE_DBX_HOST"], os.environ["PACKSENSE_PIPELINE_TOKEN"],
                       base=os.environ.get("PACKSENSE_LANDING", "/Volumes/workspace/packsense/landing"))


@dag(schedule="0 9 * * 2", start_date=datetime(2026, 10, 20), catchup=False, max_active_runs=1, tags=["p9", "reconcile"],
     params={"max_codes": 0},                                                   # 0 = every candidate; a drill is triggered with {"max_codes": 24}
     default_args={"retries": 3, "retry_delay": timedelta(minutes=2)})            # a hiccup in the Files API must not end a 2.5-hour run (lookup_batch sets its own)
def packsense_reconcile():
    @task.sensor(poke_interval=900, timeout=12 * 3600, mode="reschedule")
    def wait_for_candidates() -> PokeReturnValue:
        name = lib.newest_candidates_file(landing().list("reconcile/candidates"))
        return PokeReturnValue(is_done=name is not None, xcom_value=name)

    @task
    def read_candidates(name: str) -> dict:
        import json
        doc = json.loads(landing().read(f"reconcile/candidates/{name}"))
        limit = int(get_current_context()["params"].get("max_codes") or 0)
        codes = doc["codes"][:limit] if limit > 0 else doc["codes"]
        return {"date": doc["snapshot_date"], "batches": lib.chunk(codes), "count": len(codes)}

    @task(pool=POOL, retries=4, retry_delay=timedelta(minutes=15), retry_exponential_backoff=True, max_retry_delay=timedelta(hours=2),
          execution_timeout=timedelta(hours=1))
    def lookup_batch(batch: list, date: str) -> dict:
        return lib.run_batch(batch, f"{RESULT_ROOT}/{date}")

    @task(trigger_rule="all_done")
    def upload(plan: dict, _results=None) -> dict:
        codes = [c for b in plan["batches"] for c in b]
        lines = lib.collect(codes, f"{RESULT_ROOT}/{plan['date']}")
        landing().write(f"reconcile/results/{plan['date']}.jsonl", lib.to_jsonl(lines).encode("utf-8"))
        answered = sum(1 for x in lines if x["status"] != "unconfirmed")
        return {"date": plan["date"], "candidates": len(codes), "answered": answered, "unconfirmed": len(codes) - answered}

    @task
    def batches_of(plan: dict) -> list:
        return plan["batches"]                  # Airflow 3 maps only over a task's WHOLE return value, never over one key of it (found on the first import)

    @task
    def date_of(plan: dict) -> str:
        return plan["date"]

    plan = read_candidates(wait_for_candidates())
    results = lookup_batch.partial(date=date_of(plan)).expand(batch=batches_of(plan))
    upload(plan, results)


packsense_reconcile()
