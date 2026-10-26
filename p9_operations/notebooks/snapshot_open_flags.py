# Databricks notebook source
# ruff: noqa: E402  (the pip install and the Python restart come before the imports)
# The open flags and product features of each weekly OFF snapshot (P9 operations, Phase D item 17: the triage model's examples).
#
# `snapshot_flag_events` keeps only CHANGES, so a flag that stays open is in no table, and a model that learns "which open flags get fixed"
# needs the flags that did NOT get fixed too. For every weekly snapshot that is not in `snapshot_open_flags_manifest` yet this reads the same
# columns as `snapshot_events.py` (about 270 MB through the signed CDN address, DuckDB pinned to 1.5.6 for the same reason) in its own worker
# process and keeps one row per product and open flag in scope: every error flag, and the warning flags of the nutrition-number families the
# labelling gate covers (`snapshot_lib.WARNING_SCOPE`). Measured 2026-10-18: about 900,000 rows per snapshot. From the same pass it keeps, for the
# flagged products only, what the product looked like THEN (`snapshot_features`: serving size, first brand tag, category tags, the core nutrients per
# 100 g), because today's numbers would contain the fix. Before anything is written the worker checks the Parquet schema and validates its own
# output, and this notebook checks the row counts it wrote before the manifest row; `preflight=true` checks the schema of every snapshot and writes nothing.
#
# Bounds, as in `snapshot_events.py`: a byte guard per read, `max_snapshots` per run, a stop when the worker's memory or the time per snapshot runs
# away. A snapshot is idempotent: its rows are deleted and rewritten and the manifest row is written LAST. No contributor field is read.

# COMMAND ----------
# MAGIC %pip install -q duckdb==1.5.6

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time


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

# COMMAND ----------
dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("schema", "workspace.packsense_snapshots")
dbutils.widgets.text("weeks", "13")
dbutils.widgets.text("max_snapshots", "15")
dbutils.widgets.text("retention_months", str(lib.RETENTION_MONTHS))
dbutils.widgets.text("dry_run", "false")
dbutils.widgets.text("byte_guard_mb", str(lib.BYTE_GUARD // 1_000_000))      # the flag read of one snapshot
dbutils.widgets.text("feature_guard_mb", str(lib.FEATURE_GUARD // 1_000_000))  # the feature read of one snapshot
dbutils.widgets.text("preflight", "false")                                    # true: check every snapshot's schema, write nothing

RUN_ID = dbutils.widgets.get("run_id")
SCHEMA = dbutils.widgets.get("schema")
WEEKS = int(dbutils.widgets.get("weeks"))
MAX_SNAPSHOTS = int(dbutils.widgets.get("max_snapshots"))
RETENTION = int(dbutils.widgets.get("retention_months"))
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
BYTE_GUARD = int(dbutils.widgets.get("byte_guard_mb")) * 1_000_000
FEATURE_GUARD = int(dbutils.widgets.get("feature_guard_mb")) * 1_000_000
PREFLIGHT = dbutils.widgets.get("preflight").strip().lower() == "true"

# COMMAND ----------
from pyspark.sql import types as T  # noqa: E402

FLAG_SCHEMA = T.StructType([
    T.StructField("snapshot_sha", T.StringType()), T.StructField("snapshot_date", T.DateType()), T.StructField("code", T.StringType()),
    T.StructField("severity", T.StringType()), T.StructField("flag", T.StringType()), T.StructField("family", T.StringType()),
    T.StructField("lm", T.LongType())])
MANIFEST_SCHEMA = T.StructType([
    T.StructField("snapshot_sha", T.StringType()), T.StructField("snapshot_date", T.DateType()), T.StructField("flag_rows", T.LongType()),
    T.StructField("products_with_flags", T.LongType()), T.StructField("products_in_snapshot", T.LongType()), T.StructField("rx_mb", T.LongType()),
    T.StructField("seconds", T.DoubleType()), T.StructField("job_run_id", T.StringType()), T.StructField("finished_at", T.TimestampType()),
    T.StructField("feature_rows", T.LongType()), T.StructField("products_with_nutrients", T.LongType())])
FEATURE_SCHEMA = T.StructType([
    T.StructField("snapshot_sha", T.StringType()), T.StructField("snapshot_date", T.DateType()), T.StructField("code", T.StringType()),
    T.StructField("lm", T.LongType()), T.StructField("serving_size", T.StringType()), T.StructField("brand", T.StringType()),
    T.StructField("categories", T.ArrayType(T.StringType())), T.StructField("nutrients", T.MapType(T.StringType(), T.DoubleType())),
    T.StructField("n_nutrients", T.IntegerType()), T.StructField("max_mass_g", T.DoubleType())])


def append(table, rows, schema, batch=50000):
    """Append rows in batches (Spark Connect needs bounded createDataFrame calls)."""
    for i in range(0, len(rows), batch):
        spark.createDataFrame(rows[i:i + batch], schema).write.mode("append").saveAsTable(f"{SCHEMA}.{table}")


def count_where(table, sha):
    return spark.sql(f"select count(*) from {SCHEMA}.{table} where snapshot_sha = '{sha}'").collect()[0][0]


def prepare_tables():
    for name, sql in lib.ddl(SCHEMA).items():
        spark.sql(sql)
    # the manifest table of the first (flags only) version has no feature columns: add them once
    have = {r[0] for r in spark.sql(f"describe {SCHEMA}.snapshot_open_flags_manifest").collect()}
    for col in ("feature_rows", "products_with_nutrients"):
        if col not in have:
            spark.sql(f"alter table {SCHEMA}.snapshot_open_flags_manifest add columns ({col} bigint)")


def run_worker(s, work, total_mb, check_only):
    spec = {"sha": s.sha, "out": f"{work}/{s.sha[:12]}.json", "memory_limit_mb": int(0.5 * total_mb), "temp_dir": f"{work}/spill",
            "threads": 8, "byte_guard": BYTE_GUARD, "feature_guard": FEATURE_GUARD, "check_only": check_only}
    spec_path = f"{work}/{s.sha[:12]}.spec.json"
    with open(spec_path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh)
    proc = subprocess.run([sys.executable, os.path.join(find_p9(), "snapshot_lib.py"), "flags-worker", spec_path], capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"snapshot {s.sha[:8]} ({s.date.date()}): the worker process ended with code {proc.returncode} (-9 means killed for memory). "
                           f"stderr: {proc.stderr[-700:]}")
    with open(spec["out"], encoding="utf-8") as fh:
        res = json.load(fh)
    os.remove(spec["out"])
    return res


def run():
    prepare_tables()
    done = {r[0] for r in spark.sql(f"select snapshot_sha from {SCHEMA}.snapshot_open_flags_manifest where feature_rows is not null").collect()}
    now = dt.datetime.now(dt.timezone.utc)
    snaps = lib.pick_snapshots(lib.fetch_commits(), lib.weekly_targets(now, WEEKS))
    todo = [s for s in reversed(snaps) if s.sha not in done][:MAX_SNAPSHOTS]            # newest first: the newest is the one the weekly job needs
    print(f"{len(snaps)} weekly snapshots ({snaps[0].date.date()} to {snaps[-1].date.date()}), {len(done)} done, {len(todo)} to do this run (cap {MAX_SNAPSHOTS})")
    for s in todo:
        print(f"  {s.date.date()} {s.sha[:8]}")
    if DRY or not todo:
        return {"snapshots": len(snaps), "done": len(done), "todo": len(todo), "dry_run": DRY, "snapshots_run": 0}

    total_mb = lib.mem_total_mb()
    work = tempfile.mkdtemp(prefix="packsense_openflags_")
    if PREFLIGHT:
        # every snapshot in the window: schema only (the footer, about 107 MB each); a changed schema is found here, not at snapshot nine
        checked = 0
        for s in reversed(snaps):
            res = run_worker(s, work, total_mb, check_only=True)
            checked += 1
            print(f"schema ok: {s.sha[:8]} ({s.date.date()}), rx {res['rx_bytes'] / 1e6:.0f} MB, {res['seconds']:.0f} s", flush=True)
        shutil.rmtree(work, ignore_errors=True)
        return {"snapshots": len(snaps), "preflight": True, "schemas_ok": checked}

    seconds_history, total_rx, run_n, stopped = [], 0, 0, ""
    for s in todo:
        t0 = time.time()
        res = run_worker(s, work, total_mb, check_only=False)               # the worker has already validated its own output
        d = s.date.date()
        flag_rows = [(s.sha, d, code, sev, tag, fam, lm) for code, lm, sev, tag, fam in res["rows"]]
        feature_rows = [(s.sha, d, code, lm, serving, brand, cats or [], dict(zip(keys or [], vals or [])), n, mx)
                        for code, lm, serving, brand, cats, keys, vals, n, mx in res["features"]]
        # idempotent write: remove whatever an interrupted run left for this snapshot, rewrite, CHECK the counts, manifest row LAST
        for table in ("snapshot_open_flags", "snapshot_features"):
            spark.sql(f"delete from {SCHEMA}.{table} where snapshot_sha = '{s.sha}'")
        spark.sql(f"delete from {SCHEMA}.snapshot_open_flags_manifest where snapshot_sha = '{s.sha}'")
        append("snapshot_open_flags", flag_rows, FLAG_SCHEMA)
        append("snapshot_features", feature_rows, FEATURE_SCHEMA)
        got_flags, got_features = count_where("snapshot_open_flags", s.sha), count_where("snapshot_features", s.sha)
        if (got_flags, got_features) != (len(flag_rows), len(feature_rows)):
            raise RuntimeError(f"snapshot {s.sha[:8]}: wrote {len(flag_rows)} flag rows and {len(feature_rows)} feature rows but the tables hold "
                               f"{got_flags} and {got_features}; no manifest row written")
        secs = time.time() - t0
        append("snapshot_open_flags_manifest", [(s.sha, d, len(flag_rows), res["products_with_flags"], res["products_in_snapshot"], round(res["rx_bytes"] / 1e6),
                                                 round(secs, 1), RUN_ID, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
                                                 len(feature_rows), res["products_with_nutrients"])], MANIFEST_SCHEMA)
        total_rx += res["rx_bytes"]
        run_n += 1
        seconds_history.append(secs)
        peak = res.get("peak_rss_mb")
        print(f"snapshot {s.sha[:8]} ({d}): {len(flag_rows)} flag rows on {res['products_with_flags']} products, {len(feature_rows)} feature rows "
              f"({res['products_with_nutrients']} with nutrients) of {res['products_in_snapshot']} | worker {res['seconds']:.0f} s, peak memory "
              f"{peak and round(peak)} MB of {total_mb:.0f} MB, rx {res['rx_bytes'] / 1e6:.0f} MB | whole {secs:.0f} s", flush=True)
        stop, why = lib.should_stop(seconds_history, peak or 0, total_mb)
        if stop and s != todo[-1]:
            stopped = why
            print(f"STOPPING EARLY, progress is saved and the next run continues: {why}")
            break

    shutil.rmtree(work, ignore_errors=True)
    cutoff = lib.retention_cutoff(now, RETENTION)
    for table in ("snapshot_open_flags", "snapshot_features", "snapshot_open_flags_manifest"):
        spark.sql(f"delete from {SCHEMA}.{table} where snapshot_date < DATE'{cutoff}'")
    print(f"retention: rows of snapshots dated before {cutoff} deleted")
    return {"snapshots": len(snaps), "done": len(done), "todo": len(todo), "dry_run": False, "snapshots_run": run_n, "rx_mb": round(total_rx / 1e6),
            "stopped_early": stopped or None, "seconds_per_snapshot": [round(x) for x in seconds_history]}


result = run()
print(json.dumps(result))
dbutils.notebook.exit(json.dumps(result))
