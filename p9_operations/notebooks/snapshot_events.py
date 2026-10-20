# Databricks notebook source
# ruff: noqa: E402  (the pip install and the Python restart come before the imports)
# Flag history from OFF's weekly Hugging Face snapshots (P9 operations, Phase A).
#
# What it does: picks one snapshot per week (the newest commit of OFF's dataset at or before each Monday 00:00 UTC), and for every
# consecutive pair that is not in `snapshot_manifest` yet it reads the columns that matter from both (code, last_modified_t and the three
# data-quality tag lists, about 310 MB each, through the signed CDN address), compares them in DuckDB, and keeps only the changes:
# `snapshot_flag_events` (a flag disappeared from or appeared on a product), `snapshot_presence_events` (a product left), the open-flag counts
# of each snapshot and a manifest row. The snapshots themselves are never stored. What the logic is and why is in p9_operations/snapshot_lib.py.
#
# Bounds, because Databricks Free Edition publishes no storage or daily compute cap: a byte guard stops any single read above 1 GB, `max_pairs`
# caps a run, and events older than `retention_months` are deleted at the end of a successful run. A pair is idempotent: its rows are deleted
# and rewritten, and the manifest row is written LAST, so a crash between the two is repaired by the next run.
# No contributor field is read. Nothing here needs a secret except the optional healthchecks ping.

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

import duckdb
import requests


def find_p9():
    """The folder that holds snapshot_lib.py, wherever the deployed copy of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "snapshot_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p9_operations", "snapshot_lib.py")):
                return os.path.join(p, "p9_operations")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p9_operations/snapshot_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p9())
import snapshot_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("schema", "workspace.packsense_snapshots")
dbutils.widgets.text("weeks", "12")
dbutils.widgets.text("max_pairs", "14")
dbutils.widgets.text("retention_months", str(lib.RETENTION_MONTHS))
dbutils.widgets.text("dry_run", "false")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")           # dev and tests set "false"

RUN_ID = dbutils.widgets.get("run_id")
SCHEMA = dbutils.widgets.get("schema")
WEEKS = int(dbutils.widgets.get("weeks"))
MAX_PAIRS = int(dbutils.widgets.get("max_pairs"))
RETENTION = int(dbutils.widgets.get("retention_months"))
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"

# COMMAND ----------
ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_snapshots_ping_url")
    except Exception:
        print("no healthchecks_snapshots_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    """Best effort; a failing ping never hides the real result. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


# COMMAND ----------
from pyspark.sql import types as T  # noqa: E402

EVENT_SCHEMA = T.StructType([
    T.StructField("pair_id", T.StringType()), T.StructField("date_from", T.DateType()), T.StructField("date_to", T.DateType()),
    T.StructField("code", T.StringType()), T.StructField("severity", T.StringType()), T.StructField("flag", T.StringType()),
    T.StructField("family", T.StringType()), T.StructField("event", T.StringType()), T.StructField("family_remains", T.BooleanType()),
    T.StructField("edited", T.BooleanType()), T.StructField("lm_from", T.LongType()), T.StructField("lm_to", T.LongType())])
PRESENCE_SCHEMA = T.StructType([
    T.StructField("pair_id", T.StringType()), T.StructField("date_from", T.DateType()), T.StructField("date_to", T.DateType()),
    T.StructField("code", T.StringType()), T.StructField("event", T.StringType()), T.StructField("lm_from", T.LongType())])
OPEN_SCHEMA = T.StructType([
    T.StructField("snapshot_sha", T.StringType()), T.StructField("snapshot_date", T.DateType()), T.StructField("severity", T.StringType()),
    T.StructField("flag", T.StringType()), T.StructField("family", T.StringType()), T.StructField("open_pairs", T.LongType())])
MANIFEST_SCHEMA = T.StructType([
    T.StructField("pair_id", T.StringType()), T.StructField("snapshot_from", T.StringType()), T.StructField("snapshot_to", T.StringType()),
    T.StructField("date_from", T.DateType()), T.StructField("date_to", T.DateType()), T.StructField("rows_from", T.LongType()),
    T.StructField("rows_to", T.LongType()), T.StructField("in_both", T.LongType()), T.StructField("left_count", T.LongType()),
    T.StructField("entered_count", T.LongType()), T.StructField("edited_count", T.LongType()), T.StructField("flag_events", T.LongType()),
    T.StructField("rx_mb", T.LongType()), T.StructField("seconds", T.DoubleType()), T.StructField("job_run_id", T.StringType()),
    T.StructField("finished_at", T.TimestampType())])


def append(table, rows, schema, batch=20000):
    """Append rows in batches (Spark Connect needs small createDataFrame calls)."""
    for i in range(0, len(rows), batch):
        spark.createDataFrame(rows[i:i + batch], schema).write.mode("append").saveAsTable(f"{SCHEMA}.{table}")


def run():
    for name, sql in lib.ddl(SCHEMA).items():
        spark.sql(sql)
    done = {r[0] for r in spark.sql(f"select pair_id from {SCHEMA}.snapshot_manifest").collect()}
    now = dt.datetime.now(dt.timezone.utc)
    snaps = lib.pick_snapshots(lib.fetch_commits(), lib.weekly_targets(now, WEEKS))
    if len(snaps) < WEEKS + 1:
        print(f"WARNING: only {len(snaps)} of {WEEKS + 1} weekly snapshots were found in the commit list that was read (older weeks are skipped)")
    todo = lib.pairs_to_do(snaps, done, MAX_PAIRS)
    print(f"{len(snaps)} weekly snapshots ({snaps[0].date.date()} to {snaps[-1].date.date()}), {len(done)} pairs done, {len(todo)} to do this run (cap {MAX_PAIRS})")
    for a, b in todo:
        print(f"  {a.date.date()} {a.sha[:8]} -> {b.date.date()} {b.sha[:8]}")
    if DRY or not todo:
        return {"snapshots": len(snaps), "done": len(done), "todo": len(todo), "dry_run": DRY, "pairs_run": 0}

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET threads=8")
    con.execute("SET allow_asterisks_in_http_paths = true")      # the signed CDN address has a '*' in its query string
    loaded = None                                                # the snapshot currently held in table `p`
    total_rx = 0

    def load(table, snap):
        t0 = time.time()
        with lib.ByteGuard(lib.read_rx_bytes, lib.BYTE_GUARD, con.interrupt) as g:
            con.execute(lib.load_sql(table, lib.resolve_cdn(snap.sha)))
        if g.tripped:
            raise RuntimeError(f"byte guard: reading snapshot {snap.sha[:8]} passed {lib.BYTE_GUARD / 1e6:.0f} MB; stopped")
        return g.received(), time.time() - t0

    pairs_run = 0
    for a, b in todo:
        t0 = time.time()
        rx = 0
        if loaded is None or loaded.sha != a.sha:
            con.execute("drop table if exists p")
            r, _ = load("p", a)
            rx += r
        con.execute("drop table if exists n")
        r, _ = load("n", b)
        rx += r
        res = lib.compute_pair(con, "p", "n")
        pid = lib.pair_id(a, b)
        d_from, d_to = a.date.date(), b.date.date()

        # idempotent write: remove whatever an interrupted run left for this pair, rewrite, manifest row LAST
        spark.sql(f"delete from {SCHEMA}.snapshot_flag_events where pair_id = '{pid}'")
        spark.sql(f"delete from {SCHEMA}.snapshot_presence_events where pair_id = '{pid}'")
        append("snapshot_flag_events", [(pid, d_from, d_to, e["code"], e["severity"], e["flag"], e["family"], e["event"], e["family_remains"],
                                         e["edited"], e["lm_from"], e["lm_to"]) for e in res["events"]], EVENT_SCHEMA)
        append("snapshot_presence_events", [(pid, d_from, d_to, code, "left", lm) for code, lm in res["left"]], PRESENCE_SCHEMA)
        counted = {r[0] for r in spark.sql(f"select distinct snapshot_sha from {SCHEMA}.snapshot_open_counts").collect()}
        for table, snap in (("p", a), ("n", b)):
            if snap.sha not in counted:
                append("snapshot_open_counts", [(snap.sha, snap.date.date(), sev, tag, lib.family_key(tag), n)
                                                for sev, tag, n in lib.open_counts(con, table)], OPEN_SCHEMA)
        s = res["stats"]
        secs = time.time() - t0
        append("snapshot_manifest", [(pid, a.sha, b.sha, d_from, d_to, s["rows_from"], s["rows_to"], s["in_both"], s["left_count"], s["entered_count"],
                                      s["edited_count"], s["flag_events"], round(rx / 1e6), round(secs, 1), RUN_ID, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))],
               MANIFEST_SCHEMA)
        print(f"pair {pid}: {s} rx {rx / 1e6:.0f} MB, {secs:.0f} s")
        total_rx += rx
        pairs_run += 1
        # the newer snapshot becomes the older one of the next pair, without reading it again
        con.execute("drop table if exists p")
        con.execute("alter table n rename to p")
        loaded = b

    cutoff = lib.retention_cutoff(now, RETENTION)
    for table in ("snapshot_flag_events", "snapshot_presence_events", "snapshot_manifest"):
        spark.sql(f"delete from {SCHEMA}.{table} where date_to < DATE'{cutoff}'")
    spark.sql(f"delete from {SCHEMA}.snapshot_open_counts where snapshot_date < DATE'{cutoff}'")
    print(f"retention: rows with a newer-snapshot date before {cutoff} deleted")
    return {"snapshots": len(snaps), "done": len(done), "todo": len(todo), "dry_run": False, "pairs_run": pairs_run, "rx_mb": round(total_rx / 1e6)}


ping("/start")
try:
    result = run()
except Exception as e:                       # the message is cut short: it never carries more than a short reason
    ping("/fail", f"snapshot events failed: {type(e).__name__}: {str(e)[:200]}")
    raise
ping("", json.dumps(result))
print(json.dumps(result))
dbutils.notebook.exit(json.dumps(result))
