# Databricks notebook source
# Taxonomy load: the snapshots of OFF's taxonomies in landing -> workspace.packsense_silver.silver_taxonomy_tag
#
# What a row becomes is decided by p2_lakehouse/silver_lib/taxonomy.py (plain Python, unit-tested on real excerpts) and by the allowlist
# in p2_lakehouse/contracts/taxonomy.yml. The snapshot files in landing are the immutable raw copy (B2 and the Hugging Face archive
# hold them too), so there is no bronze table: each silver row carries the snapshot key and its sha256.
#
# Which snapshots are pending: the capture writes a daily log (taxonomies/manifests/<stamp>.json) naming every taxonomy's current
# snapshot; a snapshot is "done" when it has a row in silver_taxonomy_manifest. Per pending snapshot, in order of its valid_from:
#   1. read the landed file and check it is exactly what the capture hashed (sha256) and has the tag count the capture logged;
#   2. rows: insert-only MERGE on (taxonomy, snapshot, tag);
#   3. hand-off check: rows stored for the snapshot must equal the tags kept;
#   4. only then the manifest row (written last, like bronze and silver).
# A crash anywhere leaves the snapshot "not done"; the re-run merges 0 new rows and then records it. Problems (a file that fails its
# hash, an unbalanced hand-off, a share of skipped tags that suggests OFF changed its tag format) do not stop the other snapshots; the
# run fails at the end so the job goes red, and the `core` healthcheck gets a /fail ping. This task runs after silver and sends no
# success ping of its own (silver's ping is the success signal for the core check).

# COMMAND ----------
import collections
import datetime as dt
import json
import os
import sys

import requests


def find_p2_lakehouse():
    """The folder that holds silver_lib, wherever the git checkout or the deployed copy of this job lives."""
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
from silver_lib import contract, schema, taxonomy  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("silver_schema", "workspace.packsense_silver")     # tests and dev point this at another schema
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")                         # dev and tests set "false"
dbutils.widgets.text("only_taxonomies", "")                               # tests: comma-separated names; empty = all
dbutils.widgets.text("max_skipped_share", "0.01")

RUN_ID = dbutils.widgets.get("run_id")
LANDING = dbutils.widgets.get("landing").rstrip("/")
SILVER_SCHEMA = dbutils.widgets.get("silver_schema")
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
ONLY = {x.strip() for x in dbutils.widgets.get("only_taxonomies").split(",") if x.strip()}
MAX_SKIPPED = float(dbutils.widgets.get("max_skipped_share"))

C = taxonomy.relocate(taxonomy.load(), silver_schema=SILVER_SCHEMA)
S = contract.load()          # the scrub patterns come from the silver contract
ROOT = f"{LANDING}/{C['landing_prefix']}"
DDL = ", ".join(f"{c['name']} {schema.spark_type(c['type'])}" for c in C["columns"])

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_core_ping_url") if PING else None


def ping_fail(body):
    """Best effort: a failing ping must never fail the load. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + "/fail", data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SILVER_SCHEMA}")
for ddl in taxonomy.all_table_sql(C):
    spark.sql(ddl)

logs = []
for name in sorted(os.listdir(f"{ROOT}/manifests")):
    with open(f"{ROOT}/manifests/{name}", encoding="utf-8") as fh:
        logs.append(json.load(fh))
done = {r[0] for r in spark.table(C["manifest_table"]).select("snapshot").collect()}
todo = taxonomy.entries_to_load(logs, done, ONLY or None)
print(f"{len(logs)} daily logs, {len(done)} snapshots already in silver, {len(todo)} to load")

# COMMAND ----------
BATCH = 2000


def merge_insert_only(df, view):
    df.createOrReplaceTempView(view)
    spark.sql(f"MERGE INTO {C['table']} t USING {view} s ON t.taxonomy = s.taxonomy AND t.snapshot = s.snapshot AND t.tag = s.tag "
              "WHEN NOT MATCHED THEN INSERT *")


problems, tot = [], collections.Counter()
loaded = 0
for entry in todo:
    key = entry["snapshot"]
    try:
        with open(f"{ROOT}/{key}", "rb") as fh:
            raw = taxonomy.verify_snapshot(fh.read(), entry)                       # 1. exactly what the capture hashed
        rows, stats = taxonomy.parse_snapshot(entry["taxonomy"], raw, C, S)
        if entry.get("tags") is not None and stats["tags_in"] != entry["tags"]:
            raise RuntimeError(f"the file holds {stats['tags_in']} tags, the capture logged {entry['tags']}")
        now = dt.datetime.utcnow()
        data = [(r["taxonomy"], r["tag"], key, entry["sha256"], entry["valid_from"], r["name_en"], r["names"], r["parents"],
                 r["children"], r["props"], now, RUN_ID) for r in rows]
        for i in range(0, len(data), BATCH):                                       # 2. rows
            merge_insert_only(spark.createDataFrame(data[i:i + BATCH], schema=DDL), "incoming_taxonomy")
        stored = spark.table(C["table"]).where((spark.table(C["table"]).taxonomy == entry["taxonomy"]) &
                                               (spark.table(C["table"]).snapshot == key)).count()
        if stored != len(rows):                                                    # 3. hand-off check
            raise RuntimeError(f"stored rows do not add up: {stored} stored, {len(rows)} parsed")
        spark.createDataFrame([(key, entry["taxonomy"], entry["sha256"], stats["tags_in"], stats["tags_silver"], stats["tags_skipped"],
                                stats["values_scrubbed"], now, RUN_ID)],                 # 4. the manifest row is the last write
                              schema="snapshot STRING, taxonomy STRING, snapshot_sha256 STRING, tags_in BIGINT, tags_silver BIGINT, "
                                     "tags_skipped BIGINT, values_scrubbed BIGINT, processed_at TIMESTAMP, job_run_id STRING"
                              ).write.mode("append").saveAsTable(C["manifest_table"])
        loaded += 1
        tot.update(stats)
        if stats["tags_in"] and stats["tags_skipped"] / stats["tags_in"] > MAX_SKIPPED:
            problems.append(f"{key}: {stats['tags_skipped']} of {stats['tags_in']} tags skipped: OFF may have changed its tag format")
        print(f"{key}: {stats['tags_in']:,} tags -> {stats['tags_silver']:,} rows, {stats['tags_skipped']} skipped, "
              f"{stats['values_scrubbed']} values scrubbed")
    except Exception as e:
        # the message is cut short on purpose
        problems.append(f"{key}: {type(e).__name__}: {str(e)[:120]}")
        print("FAILED", key, type(e).__name__)

# COMMAND ----------
summary = {"snapshots_loaded": loaded, "tags_in": tot["tags_in"], "tags_silver": tot["tags_silver"], "tags_skipped": tot["tags_skipped"],
           "values_scrubbed": tot["values_scrubbed"], "problems": len(problems)}
print(json.dumps(summary))
if problems:
    ping_fail("taxonomy: " + "; ".join(problems))
    raise RuntimeError("taxonomy load finished with problems:\n" + "\n".join(problems))
dbutils.notebook.exit(json.dumps(summary))
