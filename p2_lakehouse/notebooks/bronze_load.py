# Databricks notebook source
# Bronze load: landed OFF delta files -> workspace.packsense_bronze.bronze_delta_raw
#
# Bronze keeps each record exactly as received (raw JSON text) with its key fields and lineage (source file + the
# file's sha256 from the capture manifest). It is append-only: an insert-only MERGE on (code, last_modified_t).
#
# Safe to run twice, and to re-run after a crash:
#   * a file is "done" only when it has a row in bronze_manifest, and that row is written AFTER the table write succeeds;
#   * a crash between the two leaves the data in place, the re-run merges 0 new rows and then records the file.
# Hand-off check: the rows read from each file must equal the line count the capture recorded in its manifest.
# A file with no capture-manifest entry, a different row count or a conflicting sha256 is not loaded; the job fails
# at the end (after loading everything else) so the run goes red and the problem is visible.

# COMMAND ----------
import os
import json

from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType, TimestampType

dbutils.widgets.text("run_id", "manual")
# the two paths default to production; tests point them at a scratch area
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("bronze_schema", "workspace.packsense_bronze")
RUN_ID = dbutils.widgets.get("run_id")

LANDING = dbutils.widgets.get("landing")
BRONZE = dbutils.widgets.get("bronze_schema")
RAW = f"{BRONZE}.bronze_delta_raw"
MANIFEST = f"{BRONZE}.bronze_manifest"

spark.sql(f"""CREATE TABLE IF NOT EXISTS {RAW} (
    code STRING, last_modified_t BIGINT, source_file STRING, file_sha256 STRING, ingested_at TIMESTAMP, raw_json STRING
) USING DELTA""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {MANIFEST} (
    file_name STRING, file_sha256 STRING, lines_expected BIGINT, rows_read BIGINT, rows_inserted BIGINT,
    processed_at TIMESTAMP, job_run_id STRING
) USING DELTA""")

# COMMAND ----------
# What the capture recorded for each landed file (name -> sha256 and line count).
expected, conflicts = {}, []
for m in sorted(os.listdir(f"{LANDING}/manifests")):
    with open(f"{LANDING}/manifests/{m}", encoding="utf-8") as fh:
        for entry in json.load(fh).get("files", []):
            seen = expected.setdefault(entry["name"], {"sha256": entry["sha256"], "lines": entry["lines"]})
            if seen["sha256"] != entry["sha256"]:
                conflicts.append(entry["name"])

landed = sorted(n for n in os.listdir(f"{LANDING}/deltas") if n.endswith(".json.gz"))
done = {r[0] for r in spark.table(MANIFEST).select("file_name").collect()}
todo = [n for n in landed if n not in done]
print(f"{len(landed)} files in landing, {len(done)} already in bronze, {len(todo)} to load")

# COMMAND ----------
problems = [f"{n}: two capture manifests disagree on the sha256" for n in sorted(set(conflicts))]
loaded = 0
manifest_schema = StructType([
    StructField("file_name", StringType()), StructField("file_sha256", StringType()), StructField("lines_expected", LongType()),
    StructField("rows_read", LongType()), StructField("rows_inserted", LongType()), StructField("processed_at", TimestampType()),
    StructField("job_run_id", StringType()),
])

for name in todo:
    if name in conflicts:
        continue
    info = expected.get(name)
    if info is None:
        problems.append(f"{name}: landed but not recorded in any capture manifest (cannot verify it)")
        continue
    lines = spark.read.text(f"{LANDING}/deltas/{name}")
    rows_read = lines.count()
    if rows_read != info["lines"]:
        problems.append(f"{name}: read {rows_read} rows, capture manifest says {info['lines']}")
        continue
    incoming = (lines.select(
        F.get_json_object("value", "$.code").alias("code"),
        F.get_json_object("value", "$.last_modified_t").cast("long").alias("last_modified_t"),
        F.lit(name).alias("source_file"), F.lit(info["sha256"]).alias("file_sha256"),
        F.current_timestamp().alias("ingested_at"), F.col("value").alias("raw_json"),
    ).dropDuplicates(["code", "last_modified_t"]))
    incoming.createOrReplaceTempView("incoming")
    # null-safe key match, so a record with a missing key cannot be inserted again on every re-run
    result = spark.sql(f"""MERGE INTO {RAW} t USING incoming s
        ON t.code <=> s.code AND t.last_modified_t <=> s.last_modified_t
        WHEN NOT MATCHED THEN INSERT *""").collect()[0]
    inserted = int(result["num_inserted_rows"])
    # the manifest row is the last write: the file counts as loaded only once its data is in
    spark.createDataFrame([(name, info["sha256"], info["lines"], rows_read, inserted, None, RUN_ID)], manifest_schema) \
        .withColumn("processed_at", F.current_timestamp()).write.mode("append").saveAsTable(MANIFEST)
    loaded += 1
    print(f"loaded {name}: {rows_read:,} rows read, {inserted:,} new in bronze")

# COMMAND ----------
total = spark.table(RAW).count()
print(f"bronze_delta_raw now holds {total:,} rows; {loaded} file(s) loaded this run")
if problems:
    raise RuntimeError("bronze load finished with problems:\n" + "\n".join(problems))
dbutils.notebook.exit(json.dumps({"files_loaded": loaded, "bronze_rows": total}))
