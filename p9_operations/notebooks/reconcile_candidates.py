# Databricks notebook source
# ruff: noqa: E402  (the pip install and the Python restart come before the imports)
# Deletion reconciliation, step 1 (weekly): which of our products is no longer in OFF's food database?
#
# It reads two columns (code, last_modified_t) of the NEWEST weekly Hugging Face snapshot (about 200 MB; a byte guard stops it at 600 MB), compares
# them with every product in silver, and writes two things:
#   1. `silver_existence_check` rows with status `present_in_snapshot` for every silver product the snapshot holds (the answer for ~97% of products, no API call);
#   2. a candidate list for the Airflow lookup DAG: landing/reconcile/candidates/<snapshot date>.json (codes only).
# A candidate is a product that is MISSING from the snapshot and whose newest version we hold is not newer than the snapshot's newest edit (a newer one may
# simply not be in the snapshot yet), and that is not already settled (existence_lib.candidates_sql). What a status means and why is in existence_lib.py.
# Rerunning is harmless: the rows of this snapshot are replaced and the candidate file is rewritten. Present rows older than 90 days are deleted (a product that
# is still present has a newer one; API answers are kept for ever). Nothing here needs a secret except the optional healthchecks ping.

# COMMAND ----------
# MAGIC %pip install -q duckdb requests

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import datetime as dt
import json
import os
import sys
import time

import requests


def find_p9():
    """The folder that holds snapshot_lib.py and existence_lib.py, wherever the deployed copy of this job lives."""
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
import snapshot_lib as slib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("silver_schema", lib.DEFAULT_SCHEMA)
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("recheck_days", "14")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")          # dev and tests set "false"

RUN_ID = dbutils.widgets.get("run_id")
SILVER = dbutils.widgets.get("silver_schema")
LANDING = dbutils.widgets.get("landing").rstrip("/")
RECHECK_DAYS = int(dbutils.widgets.get("recheck_days"))
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
PRESENT_KEEP_DAYS = 90
BYTE_GUARD = 600_000_000

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
    import duckdb
    t0 = time.time()
    spark.sql(lib.ddl(SILVER))
    newest = slib.fetch_commits(pages=1)[0]
    sha, snap_time = newest["id"], slib.parse_commit_date(newest["date"])
    snap_date = snap_time.date()

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET threads=8")
    con.execute("SET allow_asterisks_in_http_paths = true")      # the signed CDN address has a '*' in its query string
    with slib.ByteGuard(slib.read_rx_bytes, BYTE_GUARD, con.interrupt) as guard:
        con.execute(f"create table snap as select code, max(last_modified_t) as lm from read_parquet('{slib.resolve_cdn(sha)}') group by code")
    if guard.tripped:
        raise RuntimeError(f"byte guard: reading snapshot {sha[:8]} passed {BYTE_GUARD / 1e6:.0f} MB; stopped")
    snap_max_lm = con.execute("select max(lm) from snap").fetchone()[0]
    n_snap = con.execute("select count(*) from snap").fetchone()[0]

    silver = spark.sql(f"select code, max(last_modified_t) as lm from {SILVER}.silver_product_versions group by code").toPandas()
    api_only = f"(select * from {SILVER}.{lib.TABLE} where evidence_source = '{lib.EVIDENCE_API}')"
    checked = spark.sql(f"select code, status, cast(unix_timestamp(checked_at) as bigint) as checked_at from ({lib.latest_status_sql(api_only)})").toPandas()
    con.register("silver_df", silver)
    con.register("checked_df", checked)
    con.execute("create table silver as select code, cast(lm as bigint) as lm from silver_df")
    con.execute("create table checked (code varchar, status varchar, checked_at bigint)")      # typed first: an empty table has no column types to infer
    con.execute("insert into checked select code, status, cast(checked_at as bigint) from checked_df")

    now_epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
    candidates = [r[0] for r in con.execute(lib.candidates_sql(snap_max_lm, now_epoch, RECHECK_DAYS)).fetchall()]
    present = [r[0] for r in con.execute("select s.code from silver s join snap using (code) order by s.code").fetchall()]
    n_silver = len(silver)
    missing = con.execute("select count(*) from silver where code not in (select code from snap)").fetchone()[0]
    print(f"snapshot {sha[:8]} {snap_time:%Y-%m-%d %H:%M} UTC: {n_snap} products, newest edit {snap_max_lm}; silver {n_silver} products, {len(present)} present, "
          f"{missing} missing, {len(candidates)} candidates to ask OFF about ({time.time() - t0:.0f} s, {guard.received() / 1e6:.0f} MB read)", flush=True)

    # 1. the present rows of THIS snapshot replace any earlier ones of it; old present rows go
    spark.sql(f"delete from {SILVER}.{lib.TABLE} where evidence_source = '{lib.EVIDENCE_SNAPSHOT}' and snapshot_sha = '{sha}'")
    ts = snap_time.astimezone(dt.timezone.utc).replace(tzinfo=None)
    for i in range(0, len(present), 20000):
        rows = [(c, ts, lib.STATUS_PRESENT, "", lib.EVIDENCE_SNAPSHOT, sha, RUN_ID) for c in present[i:i + 20000]]
        spark.createDataFrame(rows, ROW_SCHEMA).write.mode("append").saveAsTable(f"{SILVER}.{lib.TABLE}")
    cutoff = (snap_time - dt.timedelta(days=PRESENT_KEEP_DAYS)).astimezone(dt.timezone.utc).replace(tzinfo=None)
    spark.sql(f"delete from {SILVER}.{lib.TABLE} where evidence_source = '{lib.EVIDENCE_SNAPSHOT}' and checked_at < TIMESTAMP'{cutoff:%Y-%m-%d %H:%M:%S}'")

    # 2. the candidate list for Airflow, written whole and renamed into place
    out_dir = f"{LANDING}/reconcile/candidates"
    os.makedirs(out_dir, exist_ok=True)
    path = f"{LANDING}/{lib.candidates_path(snap_date)}"
    doc = {"snapshot_sha": sha, "snapshot_date": str(snap_date), "snapshot_max_lm": snap_max_lm, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "run_id": RUN_ID, "count": len(candidates), "codes": candidates}
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    os.replace(path + ".tmp", path)
    return {"snapshot": sha[:8], "snapshot_date": str(snap_date), "silver_products": n_silver, "present": len(present), "missing": missing,
            "candidates": len(candidates), "rx_mb": round(guard.received() / 1e6), "seconds": round(time.time() - t0), "candidates_file": lib.candidates_path(snap_date)}


ping("/start")
try:
    result = run()
except Exception as e:                       # the message is cut short: it never carries more than a short reason
    ping("/fail", f"reconcile candidates failed: {type(e).__name__}: {str(e)[:200]}")
    raise
ping("", json.dumps(result))
print(json.dumps(result))
dbutils.notebook.exit(json.dumps(result))
