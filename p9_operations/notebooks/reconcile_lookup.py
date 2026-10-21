# Databricks notebook source
# Deletion reconciliation, daily lookup (the full-automation aim: no laptop in the data path; context file A67).
#
# Reads the newest candidate list the weekly candidate job left in the landing volume, skips the codes that already have an API answer newer than that list (from this job or
# from the Airflow second path), and asks OFF's API about the next `cap` codes, one at a time, with the same retries, backoff and 3 s pause as the Airflow version
# (p9_operations/airflow/reconcile_dag_lib.py `lookup_one`). Answers are appended to `silver_existence_check` after every 50 codes, so an interrupted run keeps its progress.
# It stops by itself, progress saved, after 3 codes in a row stay rate limited or when the time budget is used up; those codes are asked again the next day.
# A code whose only answers are `unconfirmed` is asked again the next day too, up to 3 times per candidate list. Logic and measurements: p9_operations/lookup_lib.py.
# Not retried automatically by Databricks (a retry would ask the same codes again). Nothing here needs a secret except the optional healthchecks ping.

# COMMAND ----------
# MAGIC %pip install -q requests

# COMMAND ----------
import datetime as dt
import json
import os
import sys

import requests


def find_p9():
    """The folder that holds lookup_lib.py, wherever the deployed copy of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "lookup_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p9_operations", "lookup_lib.py")):
                return os.path.join(p, "p9_operations")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p9_operations/lookup_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p9())
import existence_lib as rl  # noqa: E402
import lookup_lib as lib  # noqa: E402
import reconcile_dag_lib as dag  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("silver_schema", rl.DEFAULT_SCHEMA)
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("cap", str(lib.DEFAULT_CAP))
dbutils.widgets.text("pause_seconds", str(rl.API_PAUSE_SECONDS))
dbutils.widgets.text("budget_minutes", str(lib.DEFAULT_BUDGET_MINUTES))
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")          # dev and tests set "false"

RUN_ID = dbutils.widgets.get("run_id")
SILVER = dbutils.widgets.get("silver_schema")
LANDING = dbutils.widgets.get("landing").rstrip("/")
CAP = int(dbutils.widgets.get("cap"))
PAUSE = float(dbutils.widgets.get("pause_seconds"))
BUDGET_MINUTES = float(dbutils.widgets.get("budget_minutes"))
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
MAX_UNCONFIRMED_PER_CYCLE = 3

# COMMAND ----------
ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_reconcile_lookup_ping_url")
    except Exception:
        print("no healthchecks_reconcile_lookup_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


# COMMAND ----------
from pyspark.sql import types as T  # noqa: E402

ROW_SCHEMA = T.StructType([
    T.StructField("code", T.StringType()), T.StructField("checked_at", T.TimestampType()), T.StructField("status", T.StringType()),
    T.StructField("detail", T.StringType()), T.StructField("evidence_source", T.StringType()), T.StructField("snapshot_sha", T.StringType()),
    T.StructField("job_run_id", T.StringType())])


def run():
    spark.sql(rl.ddl(SILVER))
    folder = f"{LANDING}/reconcile/candidates"
    names = os.listdir(folder) if os.path.isdir(folder) else []
    newest = dag.newest_candidates_file(names)
    if newest is None:
        return {"note": "no candidate list in the landing volume yet", "asked": 0}
    with open(f"{folder}/{newest}", encoding="utf-8") as fh:
        doc = json.load(fh)
    since = dt.datetime.fromisoformat(doc["generated_at"]).astimezone(dt.timezone.utc).replace(tzinfo=None)
    # answered in this cycle = a clear API answer newer than the list, or MAX_UNCONFIRMED_PER_CYCLE unconfirmed answers (asked enough times)
    answered = {r[0] for r in spark.sql(
        f"select code from {SILVER}.{rl.TABLE} where evidence_source = '{rl.EVIDENCE_API}' and checked_at > TIMESTAMP'{since:%Y-%m-%d %H:%M:%S}' "
        f"group by code having sum(case when status <> '{rl.STATUS_UNCONFIRMED}' then 1 else 0 end) > 0 "
        f"or sum(case when status = '{rl.STATUS_UNCONFIRMED}' then 1 else 0 end) >= {MAX_UNCONFIRMED_PER_CYCLE}").collect()}
    pending = lib.select_pending(doc["codes"], answered, CAP)
    print(f"candidate list {newest}: {doc['count']} codes, {len(answered)} already answered this cycle, {len(pending)} to ask now (cap {CAP})", flush=True)

    def write_batch(lines):
        rows = lib.table_rows(lines, RUN_ID)
        spark.createDataFrame(rows, ROW_SCHEMA).write.mode("append").saveAsTable(f"{SILVER}.{rl.TABLE}")

    summary = lib.run_lookups(pending, write_batch, pause=PAUSE, budget_seconds=BUDGET_MINUTES * 60)
    summary.update({"candidate_list": newest, "remaining_after_run": max(0, doc["count"] - len(answered) - summary["written"])})
    return summary


ping("/start")
try:
    result = run()
except Exception as e:                       # the message is cut short: it never carries more than a short reason
    ping("/fail", f"reconcile lookup failed: {type(e).__name__}: {str(e)[:200]}")
    raise
print(json.dumps(result))
if result.get("stopped") and "rate limited" in str(result.get("stopped")):
    ping("/fail", "reconcile lookup stopped: " + json.dumps(result))      # visible, but the progress is saved and tomorrow continues
else:
    ping("", json.dumps(result))
dbutils.notebook.exit(json.dumps(result))
