# Databricks notebook source
# Pipeline-health collector (roadmap Phase B item 9). Once a day, in an admin-owned job (no service principal can be granted the system tables on Free Edition), it writes operating facts
# about the pipeline into workspace.packsense_health.health_metric_daily: job runs and durations (system.lakeflow) and
# whether every outside service answers (the same light requests as the monthly egress check). It reads no product data and no billing table.
#
# Prints counts and names only. Rows are merged by (day, subject, metric), so a rerun never duplicates. An unreachable service turns the task red and
# sends /fail with the service names, AFTER the rows are written (the page should show the outage, not hide it).
# Widgets: dry_run=true runs the queries and the requests and prints the row counts but writes nothing.

# COMMAND ----------
import datetime as dt
import json
import os
import sys

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
            if os.path.isfile(os.path.join(p, "health_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p9_operations", "health_lib.py")):
                return os.path.join(p, "p9_operations")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p9_operations/health_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p9())
import egress_lib  # noqa: E402
import health_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("secret_scope", "packsense_health")
dbutils.widgets.text("ping_healthchecks", "true")
dbutils.widgets.text("dry_run", "false")
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
LANDING = dbutils.widgets.get("landing").strip().rstrip("/")
SCOPE = dbutils.widgets.get("secret_scope").strip()
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
RUN_ID = dbutils.widgets.get("run_id")

ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_health_ping_url")
    except Exception:
        print("no healthchecks_health_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


# COMMAND ----------
try:
    ping("/start")
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    today = now.date()
    stamp = now.replace(microsecond=0)

    jobs = [tuple(r) for r in spark.sql(lib.job_runs_sql(today)).collect()]
    last = [tuple(r) for r in spark.sql(lib.last_success_sql(today)).collect()]
    results = egress_lib.check_all()
    for r in results:
        print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['service']}: {r['detail']} ({r['seconds']} s)")

    # 'Right now' timestamps: the newest OFF file and when we received it (capture manifests in the landing volume), and the last good gold build.
    # Not critical: if the manifests cannot be read the job still writes everything else and says so.
    arrival = None
    try:
        names = sorted(e.name for e in os.scandir(LANDING + "/manifests") if e.name.endswith(".json"))[-lib.MANIFESTS_TO_READ:]
        arrival = lib.newest_arrival([json.load(open(f"{LANDING}/manifests/{n}", encoding="utf-8")) for n in names])
    except Exception as e:
        print("WARNING: capture manifests not read:", type(e).__name__)
    gold_last = dict(last).get("packsense-gold-build")
    right_now = lib.pipeline_rows(arrival, gold_last, today, stamp, RUN_ID)
    print(f"right now: {[r['metric'] for r in right_now]}")

    rows = (lib.job_rows(jobs, stamp, RUN_ID) + lib.success_age_rows(last, today, now, stamp, RUN_ID)
            + lib.service_rows(results, today, stamp, RUN_ID) + right_now)
    print(f"rows: job runs {len(jobs)} groups, last success {len(last)} jobs, services {len(results)}, right now {len(right_now)}, total {len(rows)}")

    if DRY:
        print("dry_run: nothing written")
    else:
        if not spark.catalog.tableExists(lib.FULL_TABLE):       # the admin makes the table (setup_health.py create-schema)
            raise RuntimeError(f"{lib.FULL_TABLE} does not exist: run p9_operations/bootstrap/setup_health.py create-schema")
        from pyspark.sql import types as T
        schema = T.StructType([
            T.StructField("metric_date", T.DateType()), T.StructField("subject", T.StringType()), T.StructField("metric", T.StringType()),
            T.StructField("value", T.DoubleType()), T.StructField("unit", T.StringType()), T.StructField("detail", T.StringType()),
            T.StructField("collected_at", T.TimestampType()), T.StructField("job_run_id", T.StringType()),
        ])
        df = spark.createDataFrame([tuple(r[c] for c in lib.COLUMNS) for r in rows], schema)
        df.createOrReplaceTempView("health_rows")
        spark.sql(lib.merge_sql("health_rows"))
        print("merged", len(rows), "rows into", lib.FULL_TABLE)

    bad = lib.failures(results)
    if bad:
        text = "services not reachable: " + "; ".join(bad)
        ping("/fail", text)
        raise RuntimeError(text)
    ping("", f"{len(rows)} rows, {len(results)} services reachable")
    summary = json.dumps({"rows": len(rows), "failed_services": 0})
except Exception as e:
    if "services not reachable" not in str(e):
        ping("/fail", f"{type(e).__name__}: {str(e)[:400]}")
    raise

# COMMAND ----------
# outside the try on purpose: dbutils.notebook.exit works by raising, and the handler above would report it as a failure
dbutils.notebook.exit(summary)
