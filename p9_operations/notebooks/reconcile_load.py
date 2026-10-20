# Databricks notebook source
# Deletion reconciliation, step 3: load the answers the Airflow lookup DAG left in the landing volume into `silver_existence_check`.
#
# Every landing/reconcile/results/<date>.jsonl is read, validated (a line with no code, an unknown status or bad JSON refuses the WHOLE file: nothing is guessed
# or skipped) and appended with evidence_source `off_api_v2`. A file is identified by its name (the `job_run_id` of its rows is `results:<name>`), so loading it
# twice replaces its rows instead of doubling them. Nothing is deleted from the landing volume here. No secret is needed except the optional ping.

# COMMAND ----------
import datetime as dt
import json
import os
import sys
import time
from collections import Counter

import requests


def find_p9():
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "existence_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p9_operations", "existence_lib.py")):
                return os.path.join(p, "p9_operations")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p9_operations/existence_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p9())
import existence_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("silver_schema", lib.DEFAULT_SCHEMA)
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")          # dev and tests set "false"

RUN_ID = dbutils.widgets.get("run_id")
SILVER = dbutils.widgets.get("silver_schema")
LANDING = dbutils.widgets.get("landing").rstrip("/")
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"

# COMMAND ----------
ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_reconcile_ping_url")
    except Exception:
        print("no healthchecks_reconcile_ping_url in the scope: running without a ping")


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
    t0 = time.time()
    spark.sql(lib.ddl(SILVER))
    folder = f"{LANDING}/reconcile/results"
    files = sorted(n for n in os.listdir(folder) if n.endswith(".jsonl")) if os.path.isdir(folder) else []
    totals, loaded = Counter(), []
    for name in files:
        with open(f"{folder}/{name}", encoding="utf-8") as fh:
            rows = lib.parse_results(fh.read())                       # a bad line refuses the whole file, by name
        marker = f"results:{name}"
        spark.sql(f"delete from {SILVER}.{lib.TABLE} where job_run_id = '{marker}'")
        data = [(r["code"], dt.datetime.strptime(r["checked_at"], "%Y-%m-%dT%H:%M:%SZ"), r["status"], r.get("detail") or "", lib.EVIDENCE_API, None, marker)
                for r in rows]
        for i in range(0, len(data), 20000):
            spark.createDataFrame(data[i:i + 20000], ROW_SCHEMA).write.mode("append").saveAsTable(f"{SILVER}.{lib.TABLE}")
        totals.update(r["status"] for r in rows)
        loaded.append({"file": name, "rows": len(rows)})
        print(f"{name}: {len(rows)} answers", flush=True)
    return {"files": loaded, "answers_by_status": dict(totals), "seconds": round(time.time() - t0)}


ping("/start")
try:
    result = run()
except Exception as e:                       # the message is cut short: it never carries more than a short reason
    ping("/fail", f"reconcile load failed: {type(e).__name__}: {str(e)[:200]}")
    raise
ping("", json.dumps(result))
print(json.dumps(result))
dbutils.notebook.exit(json.dumps(result))
