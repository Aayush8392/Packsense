# Databricks notebook source
# Schema-drift check: does the data silver just produced still look like the recent normal?
#
# Why: silver reads only the fields in contracts/silver.yml and has explicit column types, so if OFF renames or restructures a field
# the column silently arrives empty and nothing fails. The decisions (what is measured, the thresholds, what is an ALERT) are in
# p2_lakehouse/silver_lib/drift.py (plain Python, unit-tested on 14 real days and the real seed); this notebook only reads the
# numbers and writes the findings.
#
# Runs as the third task of the daily job, after silver. It never changes data and never fails the load: an ALERT turns only this task
# and its own healthchecks check red (`packsense-drift`). Each delta day and each silver run is judged once; the findings are kept in
# silver_drift_report (an alert is raised on the day it is found, the table keeps it afterwards).
#   layer 1 (per day = one delta file): share of products with a value for each nullable contract column, the nutrition-format mix,
#           products per day, schema_version values, against the last 30 earlier days;
#   layer 2 (per silver run of daily files): families of top-level field names never seen in an earlier run (a WARN, nothing breaks);
#   layer 3 (per day): how often the shape checks changed a value (dropped tags, values that do not fit their type, dropped nutrient
#           entries, nulled enums). Each day's bronze rows are run through the silver transform in memory (nothing is written to silver,
#           the hashing key is a throwaway) and only the counts are stored in silver_drift_metrics. The first run measures every
#           existing day; later runs measure the new day. If measuring fails, the report is still written and this task ends red.
# Widgets for tests: evaluate_prefix / baseline_prefix (judge another population, e.g. the seed, against the daily files).

# COMMAND ----------
import datetime as dt
import json
import os
import sys

import requests


def find_p2_lakehouse():
    """The folder that holds silver_lib, wherever the git checkout of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isdir(os.path.join(p, "silver_lib")):
                return p
            if os.path.isdir(os.path.join(p, "p2_lakehouse", "silver_lib")):
                return os.path.join(p, "p2_lakehouse")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p2_lakehouse/silver_lib; looked from " + repr(starts))


sys.path.insert(0, find_p2_lakehouse())
from pyspark.sql import functions as F  # noqa: E402
from silver_lib import contract, drift, run, schema, transform  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("silver_schema", "workspace.packsense_silver")
dbutils.widgets.text("report_schema", "")                               # tests: write the report here while reading silver from silver_schema
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")                       # tests set "false"
dbutils.widgets.text("evaluate_prefix", "openfoodfacts_products_")      # which silver source files are judged: the daily delta files
dbutils.widgets.text("baseline_prefix", "")                             # empty = each day against the days before it; else judge against these files

RUN_ID = dbutils.widgets.get("run_id")
SILVER_SCHEMA = dbutils.widgets.get("silver_schema")
REPORT_SCHEMA = dbutils.widgets.get("report_schema").strip() or SILVER_SCHEMA
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
EVAL_PREFIX = dbutils.widgets.get("evaluate_prefix")
BASE_PREFIX = dbutils.widgets.get("baseline_prefix").strip()

C = contract.relocate(contract.load(), silver_schema=SILVER_SCHEMA)
CR = contract.relocate(contract.load(), silver_schema=REPORT_SCHEMA)     # the report may live elsewhere than the silver tables (tests)
REPORT = schema.drift_report_table(CR)
METRICS = schema.drift_metrics_table(CR)
COLS = drift.coverage_columns(C)
MEASURE_KEY = "drift-measure-only-throwaway-key"      # the transform needs a key to hash identities; those hashes are discarded here

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_drift_ping_url") if PING else None


def ping(suffix="", body=None):
    """Best effort: a failing ping must never fail the check. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=(body or "")[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


ping("/start")
spark.sql(schema.drift_report_table_sql(CR))
spark.sql(schema.drift_metrics_table_sql(CR))
problems = []


def day_metrics(prefix):
    sql = drift.metrics_sql(C, C["table"], prefix)
    return [drift.metrics_from_row(r.asDict(), COLS) for r in spark.sql(sql).collect()]


def judged(kind):
    return {r[0] for r in spark.table(REPORT).where(f"subject_kind = '{kind}'").select("subject").distinct().collect()}


# COMMAND ----------
# Layer 1: the days (delta files) not judged yet.
days = day_metrics(EVAL_PREFIX)
baseline_days = day_metrics(BASE_PREFIX) if BASE_PREFIX and BASE_PREFIX != EVAL_PREFIX else None

# Layer 3 counts: measure the days that have none yet (the seed, judged against the daily files, has no counts and skips layer 3).
if baseline_days is None:
    measured = {r[0] for r in spark.table(METRICS).select("source_file").distinct().collect()}
    ctx = transform.Context(C, MEASURE_KEY)
    for d in days:
        if d["file"] in measured:
            continue
        try:
            raw = [r.asDict() for r in spark.table(C["source_table"]).where(F.col("source_file") == d["file"])
                   .select("code", "last_modified_t", "raw_json", "source_file", "file_sha256", "ingested_at").collect()]
            counts = drift.measure(run.process_batch(raw, ctx, RUN_ID, dt.datetime.utcnow()))
            spark.createDataFrame([(dt.datetime.utcnow(), RUN_ID, d["file"], m, n) for m, n in counts.items()],
                                  schema="measured_at TIMESTAMP, drift_run_id STRING, source_file STRING, metric STRING, count BIGINT"
                                  ).write.mode("append").saveAsTable(METRICS)
            print(f"measured {d['file']}: {counts[drift.ROWS_METRIC]:,} products, {len(counts) - 1} kind(s) of failure")
        except Exception as e:      # the message is cut short: it must never carry record contents into the logs
            problems.append(f"measuring {d['file']}: {type(e).__name__}: {str(e)[:120]}")
            print("MEASURE FAILED", d["file"], type(e).__name__)
    drift.attach_failures(days, drift.failures_by_file(r.asDict() for r in spark.table(METRICS).collect()))

file_results = drift.evaluate_pending(days, judged("file"), baseline_days)
print(f"{len(days)} day(s) in silver with prefix {EVAL_PREFIX!r}, {len(file_results)} to judge")

# Layer 2: silver runs of daily files (every file of the run starts with the prefix), oldest first.
run_results = []
if baseline_days is None:
    manifest = spark.table(C["manifest_table"]).select("job_run_id", "file_name", "processed_at").collect()
    by_run = {}
    for r in manifest:
        by_run.setdefault(r["job_run_id"], []).append(r)
    daily_runs = sorted(((min(x["processed_at"] for x in rows), run) for run, rows in by_run.items()
                         if all(x["file_name"].startswith(EVAL_PREFIX) for x in rows)))
    runs = [{"run": run, "fields": [r["field"] for r in spark.table(C["field_log_table"]).where(f"job_run_id = '{run}'").select("field").collect()]}
            for _, run in daily_runs]
    run_results = drift.family_pass(runs, judged("silver_run"))
    print(f"{len(runs)} silver run(s) of daily files, {len(run_results)} to judge")

# COMMAND ----------
now = dt.datetime.utcnow()
rows, findings = [], []
for kind, results in (("file", file_results), ("silver_run", run_results)):
    for subject, fs in results:
        for f in fs:
            findings.append(f)
            rows.append((now, RUN_ID, kind, subject, f.check, f.level, f.observed, f.low, f.high, f.detail))
if rows:
    spark.createDataFrame(rows, schema="evaluated_at TIMESTAMP, drift_run_id STRING, subject_kind STRING, subject STRING, check_name STRING, "
                                       "level STRING, observed DOUBLE, baseline_low DOUBLE, baseline_high DOUBLE, detail STRING"
                          ).write.mode("append").saveAsTable(REPORT)

counts = {lvl: sum(f.level == lvl for f in findings) for lvl in ("ALERT", "WARN", "WARMUP", "OK")}
text = drift.summary(findings, len(file_results), len(run_results))
print(text)
result = {"days_judged": len(file_results), "runs_judged": len(run_results), **{k.lower(): v for k, v in counts.items()}}
print(json.dumps(result))
if problems:      # the findings above are already stored; this only turns the drift check red, the load is never touched
    ping("/fail", text + " | " + "; ".join(problems))
    raise RuntimeError("drift check could not measure every day:\n" + "\n".join(problems)[:3000])
if counts["ALERT"]:
    ping("/fail", text)
    raise RuntimeError("drift check found alerts (details in " + REPORT + "):\n" + "\n".join(f.detail for f in findings if f.level == "ALERT")[:3000])
ping("", text)
dbutils.notebook.exit(json.dumps(result))
