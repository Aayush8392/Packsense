# Databricks notebook source
# Silver load: bronze rows -> workspace.packsense_silver (silver_product_versions + quarantine + bookkeeping)
#
# What a record becomes is decided by p2_lakehouse/silver_lib (plain Python, unit-tested on real records) and by the
# allowlist in p2_lakehouse/contracts/silver.yml. This notebook only reads bronze, writes the results and keeps the order
# of writes safe.
#
# Per bronze file that silver has not finished yet (a file is "done" when it has a row in silver_manifest):
#   1. identities: HMACs of the contributor names and phone numbers in the file go into silver_identity_hmacs first, so a
#      name is known even if the run dies later (insert-only; plain names are never stored);
#   2. silver rows: insert-only MERGE on (code, last_modified_t);
#   3. quarantine rows: insert-only MERGE on (source_file, record_sha256);
#   4. hand-off check: rows silver + rows quarantine for the file must equal the bronze rows for the file;
#   5. only then the manifest row (written last, like bronze).
# A crash anywhere leaves the file "not done"; the re-run merges 0 new rows and then records it.
# Problems (a file that fails, an unbalanced hand-off, a quarantine rate above the limit, a bronze task that did not
# succeed) do not stop the other files; the run fails at the end so it goes red, and healthchecks gets a /fail ping.

# COMMAND ----------
import collections
import datetime as dt
import json
import os
import sys

import requests
from pyspark.sql import functions as F


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


P2 = find_p2_lakehouse()
sys.path.insert(0, P2)
print("silver_lib found under", P2)
from silver_lib import contract, personal, run, schema, transform  # noqa: E402

dbutils.widgets.text("run_id", "manual")
# the schemas default to production; tests point them at scratch schemas
dbutils.widgets.text("bronze_schema", "workspace.packsense_bronze")
dbutils.widgets.text("silver_schema", "workspace.packsense_silver")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")           # tests set "false"
dbutils.widgets.text("bronze_result", "n/a")                 # the job passes {{tasks.bronze.result_state}}
dbutils.widgets.text("max_quarantine_rate", "0.01")
dbutils.widgets.text("only_files", "")                       # tests: comma-separated file names; empty = every pending file

RUN_ID = dbutils.widgets.get("run_id")
BRONZE_SCHEMA = dbutils.widgets.get("bronze_schema")
SILVER_SCHEMA = dbutils.widgets.get("silver_schema")
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
BRONZE_RESULT = dbutils.widgets.get("bronze_result").strip()
MAX_Q_RATE = float(dbutils.widgets.get("max_quarantine_rate"))
ONLY = [x.strip() for x in dbutils.widgets.get("only_files").split(",") if x.strip()]

C = contract.relocate(contract.load(), silver_schema=SILVER_SCHEMA, bronze_schema=BRONZE_SCHEMA)
RAW = C["source_table"]
BRONZE_MANIFEST = f"{BRONZE_SCHEMA}.bronze_manifest"
IDENT = C["personal_data_check"]["identity_table"]

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_core_ping_url") if PING else None


def ping(suffix="", body=None):
    """Best effort: a failing ping must never fail the load. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=(body or "")[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


ping("/start")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER_SCHEMA}")
for ddl in schema.all_table_sql(C):
    spark.sql(ddl)

key = dbutils.secrets.get(SCOPE, C["hmac"]["secret_key"])
problems = []
if BRONZE_RESULT not in ("n/a", "success", "SUCCESS"):
    problems.append(f"the bronze task finished as '{BRONZE_RESULT}' (silver still processed what bronze completed)")

# COMMAND ----------
# What is pending: files bronze has finished (it has a manifest row) that silver has not.
done = {r[0] for r in spark.table(C["manifest_table"]).select("file_name").collect()}
bronze_files = {r["file_name"]: r["file_sha256"] for r in spark.table(BRONZE_MANIFEST).select("file_name", "file_sha256").collect()}
todo = sorted(n for n in bronze_files if n not in done and (not ONLY or n in ONLY))
print(f"{len(bronze_files)} files finished in bronze, {len(done)} already in silver, {len(todo)} to process")

ids = spark.table(IDENT).select("hmac", "kind").collect()
ctx = transform.Context(
    C, key,
    known_users=frozenset(r["hmac"] for r in ids if r["kind"] == "username"),
    known_phones=frozenset(r["hmac"] for r in ids if r["kind"] == "phone"),
    stoplist=personal.load_stoplist(contract.stoplist_path(C)))
print(f"{len(ctx.known_users)} known usernames, {len(ctx.known_phones)} known phones, {len(ctx.stoplist)} stoplisted words (hashes only)")

# COMMAND ----------
QCOLS = ["code", "last_modified_t", "reason", "pii_columns", "payload", "source_file", "file_sha256", "record_sha256",
         "bronze_ingested_at", "quarantined_at", "job_run_id", "resolved_by_run"]
QDDL = ("code STRING, last_modified_t BIGINT, reason STRING, pii_columns ARRAY<STRING>, payload STRING, source_file STRING, "
        "file_sha256 STRING, record_sha256 STRING, bronze_ingested_at TIMESTAMP, quarantined_at TIMESTAMP, "
        "job_run_id STRING, resolved_by_run STRING")
SILVER_COLS = [c["name"] for c in C["columns"]]
SILVER_DDL = schema.struct_ddl(C)


def merge_insert_only(target, df, view, on):
    df.createOrReplaceTempView(view)
    return int(spark.sql(f"MERGE INTO {target} t USING {view} s ON {on} WHEN NOT MATCHED THEN INSERT *").collect()[0]["num_inserted_rows"])


tot = collections.Counter()
reasons, coerce, fmt = collections.Counter(), collections.Counter(), collections.Counter()
files_done = 0

for name in todo:
    try:
        now = dt.datetime.utcnow()
        rows = [r.asDict() for r in spark.table(RAW).where(F.col("source_file") == name)
                .select("code", "last_modified_t", "raw_json", "source_file", "file_sha256", "ingested_at").collect()]
        before_users, before_phones = ctx.known_users, ctx.known_phones
        res = run.process_batch(rows, ctx, RUN_ID, now)
        if not res.balanced():
            raise RuntimeError(f"batch not balanced: {res.rows_in} in, {len(res.silver)} silver + {len(res.quarantine)} quarantine")

        # 1. identities (hashes only), before anything that could fail later
        new_ids = [(h, "username", n, now, RUN_ID) for h, n in res.users.items() if h not in before_users] + \
                  [(h, "phone", n, now, RUN_ID) for h, n in res.phones.items() if h not in before_phones]
        if new_ids:
            df = spark.createDataFrame(new_ids, schema="hmac STRING, kind STRING, length INT, first_seen_at TIMESTAMP, first_seen_run STRING")
            merge_insert_only(IDENT, df, "incoming_ids", "t.hmac = s.hmac AND t.kind = s.kind")
        tot["identities_added"] += len(new_ids)

        # 2. silver rows
        if res.silver:
            df = spark.createDataFrame([tuple(r[c] for c in SILVER_COLS) for r in res.silver], schema=SILVER_DDL)
            merge_insert_only(C["table"], df, "incoming_silver", "t.code = s.code AND t.last_modified_t = s.last_modified_t")

        # 3. quarantine rows
        if res.quarantine:
            def qrow(q):
                lmt = q["last_modified_t"] if isinstance(q["last_modified_t"], int) and not isinstance(q["last_modified_t"], bool) else None
                code = None if q["code"] is None else str(q["code"])
                return tuple((code if c == "code" else lmt if c == "last_modified_t" else q[c]) for c in QCOLS)
            df = spark.createDataFrame([qrow(q) for q in res.quarantine], schema=QDDL)
            merge_insert_only(C["quarantine_table"], df, "incoming_q", "t.source_file = s.source_file AND t.record_sha256 = s.record_sha256")

        # 4. hand-off check on what is actually stored
        n_s = spark.table(C["table"]).where(F.col("source_file") == name).count()
        n_q = spark.table(C["quarantine_table"]).where(F.col("source_file") == name).count()
        if n_s + n_q != res.rows_in:
            raise RuntimeError(f"stored rows do not add up: {n_s} silver + {n_q} quarantine, bronze has {res.rows_in}")

        # 5. the manifest row is the last write
        spark.createDataFrame([(name, bronze_files[name], res.rows_in, len(res.silver), len(res.quarantine), now, RUN_ID)],
                              schema="file_name STRING, file_sha256 STRING, rows_in BIGINT, rows_silver BIGINT, rows_quarantine BIGINT, "
                                     "processed_at TIMESTAMP, job_run_id STRING").write.mode("append").saveAsTable(C["manifest_table"])
        files_done += 1
        tot["rows_in"] += res.rows_in
        tot["rows_silver"] += len(res.silver)
        tot["rows_quarantine"] += len(res.quarantine)
        tot["scrubbed"] += res.scrubbed
        tot["short_hits"] += res.short_hits
        tot["exempt_hits"] += res.exempt_hits
        reasons.update(res.reasons)
        coerce.update(res.coerce_failures)
        fmt.update(res.nutrition_format)
        print(f"{name}: {res.rows_in:,} in -> {len(res.silver):,} silver, {len(res.quarantine):,} quarantine {dict(res.reasons)}")
    except Exception as e:
        # the message is cut short: it must never carry record contents into the logs
        problems.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
        print("FAILED", name, type(e).__name__)

# COMMAND ----------
if tot["rows_in"] >= 200 and tot["rows_quarantine"] / tot["rows_in"] > MAX_Q_RATE:
    problems.append(f"quarantine rate {tot['rows_quarantine'] / tot['rows_in']:.2%} is above the limit {MAX_Q_RATE:.2%} "
                    f"(reasons {dict(reasons)}): OFF may have changed its format")

processed_at = dt.datetime.utcnow()
if files_done:
    spark.createDataFrame(
        [(RUN_ID, processed_at, C["version"], files_done, tot["rows_in"], tot["rows_silver"], tot["rows_quarantine"], dict(reasons), dict(coerce),
          dict(fmt), tot["scrubbed"], tot["short_hits"], tot["exempt_hits"], tot["identities_added"], len(ctx.field_counts))],
        schema="job_run_id STRING, processed_at TIMESTAMP, contract_version INT, files BIGINT, rows_in BIGINT, rows_silver BIGINT, "
               "rows_quarantine BIGINT, quarantine_by_reason MAP<STRING,BIGINT>, coerce_failures MAP<STRING,BIGINT>, "
               "nutrition_format MAP<STRING,BIGINT>, patterns_scrubbed BIGINT, short_name_hits BIGINT, exempt_name_hits BIGINT, "
               "identities_added BIGINT, top_level_fields_seen BIGINT").write.mode("append").saveAsTable(C["stats_table"])
    spark.createDataFrame([(RUN_ID, processed_at, f, n) for f, n in ctx.field_counts.items()],
                          schema="job_run_id STRING, processed_at TIMESTAMP, field STRING, products BIGINT"
                          ).write.mode("append").saveAsTable(C["field_log_table"])

summary = {"files_processed": files_done, "rows_in": tot["rows_in"], "rows_silver": tot["rows_silver"],
           "rows_quarantine": tot["rows_quarantine"], "quarantine_by_reason": dict(reasons), "short_name_hits": tot["short_hits"],
           "exempt_name_hits": tot["exempt_hits"], "identities_added": tot["identities_added"], "problems": len(problems)}
print(json.dumps(summary))
if problems:
    ping("/fail", "silver: " + "; ".join(problems))
    raise RuntimeError("silver load finished with problems:\n" + "\n".join(problems))
ping("", json.dumps(summary))
dbutils.notebook.exit(json.dumps(summary))
