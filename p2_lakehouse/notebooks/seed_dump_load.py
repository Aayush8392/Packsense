# Databricks notebook source
# India seed from OFF's full dump (13 parts in the private archive) into bronze, in two modes:
#
#   stage    read the dump ONCE and write the India lines to a staging schema (same tables as bronze). Resumable: a part is "done"
#            when it has a row in the stage manifest, written after its rows. The parts are one gzip stream, so a re-run still
#            decompresses the finished parts (to keep the stream in step) but writes only the rest.
#   promote  copy staged parts into the real bronze table and its manifest, SQL only (the dump is not read again). Refuses to run
#            unless silver's contract is version 3 (the legacy-nutriments mapper), so the daily silver run can never process the
#            seed with logic that would load old-format products without their nutrition.
#   drop_stage  remove the staging schema, only when every staged part is in the production manifest.
#
# What an India line is, how parts are cut and how a part is checked is in p2_lakehouse/seed_lib.py (unit-tested). Each part's
# bytes are checked against the sha256 and size in the archive manifest before any of it is used. The source_file of a row is
# seed-dump:<dump date>:part-NNNN, so silver processes the seed through its normal per-file path. Same key rule as bronze:
# insert-only MERGE on (code, last_modified_t), null-safe, so a product version already in bronze from the deltas is not added twice.
# No secret is printed or passed as a parameter; the token comes from the secret scope. No counts of personal data are produced.

# COMMAND ----------
# MAGIC %pip install -q huggingface_hub

# COMMAND ----------
import datetime as dt
import hashlib
import json
import os
import shutil
import sys

from huggingface_hub import hf_hub_download


def find_p2_lakehouse():
    """The folder that holds seed_lib.py, wherever the git checkout of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "seed_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p2_lakehouse", "seed_lib.py")):
                return os.path.join(p, "p2_lakehouse")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p2_lakehouse/seed_lib.py; looked from " + repr(starts))


P2 = find_p2_lakehouse()
sys.path.insert(0, P2)
import seed_lib as lib  # noqa: E402
from silver_lib import contract  # noqa: E402

dbutils.widgets.text("mode", "stage")                                    # stage | promote | drop_stage
dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("hf_repo", "Anonymous8392/off-catalogue-archive")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("hf_secret_name", "hf_dump_read_token")
dbutils.widgets.text("dump_date", "2026-10-13")
dbutils.widgets.text("stage_schema", "workspace.packsense_seed_stage")
dbutils.widgets.text("bronze_schema", "workspace.packsense_bronze")
dbutils.widgets.text("last_part", "all")                                 # tests: stage only parts 0000..NNNN
dbutils.widgets.text("allow_old_contract", "false")                      # tests only

MODE = dbutils.widgets.get("mode")
RUN_ID = dbutils.widgets.get("run_id")
HF_REPO = dbutils.widgets.get("hf_repo")
SCOPE = dbutils.widgets.get("secret_scope")
DUMP_DATE = dbutils.widgets.get("dump_date")
STAGE, BRONZE = dbutils.widgets.get("stage_schema"), dbutils.widgets.get("bronze_schema")
LAST = dbutils.widgets.get("last_part")
ALLOW_OLD = dbutils.widgets.get("allow_old_contract").strip().lower() == "true"
assert MODE in ("stage", "promote", "drop_stage"), MODE

RAW_DDL = """(code STRING, last_modified_t BIGINT, source_file STRING, file_sha256 STRING, ingested_at TIMESTAMP, raw_json STRING) USING DELTA"""
MAN_DDL = """(file_name STRING, file_sha256 STRING, lines_expected BIGINT, rows_read BIGINT, rows_inserted BIGINT,
              processed_at TIMESTAMP, job_run_id STRING) USING DELTA"""
ROW_SCHEMA = "code STRING, last_modified_t BIGINT, source_file STRING, file_sha256 STRING, ingested_at TIMESTAMP, raw_json STRING"
MAN_SCHEMA = ("file_name STRING, file_sha256 STRING, lines_expected BIGINT, rows_read BIGINT, rows_inserted BIGINT, "
              "processed_at TIMESTAMP, job_run_id STRING")
problems = []


def merge_insert_only(target, view):
    return int(spark.sql(f"""MERGE INTO {target} t USING {view} s
        ON t.code <=> s.code AND t.last_modified_t <=> s.last_modified_t
        WHEN NOT MATCHED THEN INSERT *""").collect()[0]["num_inserted_rows"])


def add_manifest_row(target, row):
    spark.createDataFrame([row], schema=MAN_SCHEMA).write.mode("append").saveAsTable(target)


def finish(summary):
    print(json.dumps(summary))
    if problems:
        raise RuntimeError(f"seed {MODE} finished with problems:\n" + "\n".join(problems))
    dbutils.notebook.exit(json.dumps(summary))


# COMMAND ----------
if MODE == "stage":
    tok = dbutils.secrets.get(SCOPE, dbutils.widgets.get("hf_secret_name"))
    hfm = json.load(open(hf_hub_download(HF_REPO, "dump/manifest.json", repo_type="dataset", token=tok, force_download=True)))
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {STAGE}")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {STAGE}.bronze_delta_raw {RAW_DDL}")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {STAGE}.bronze_manifest {MAN_DDL}")
    done = {r[0] for r in spark.table(f"{STAGE}.bronze_manifest").select("file_name").collect()}
    parts = lib.plan_parts(hfm, done, DUMP_DATE)
    print(f"{len(parts)} parts in the archive manifest, {sum(p['done'] for p in parts)} already staged")

    stream, staged_rows, staged_parts = lib.DumpStream(), 0, 0
    all_parts_processed = True
    for p in parts:
        if LAST != "all" and p["key"] > LAST:
            all_parts_processed = False
            break
        path = hf_hub_download(HF_REPO, f"dump/part-{p['key']}.bin", repo_type="dataset", token=tok, local_dir="/tmp/seed_parts")
        sha, size = hashlib.sha256(), 0
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                sha.update(chunk)
                size += len(chunk)
        bad = lib.verify_part(p, size, sha.hexdigest())
        if bad:                      # the stream cannot continue past a damaged part
            problems.append(bad)
            os.remove(path)
            all_parts_processed = False
            break

        def chunks():
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 22), b""):
                    yield chunk

        recs, nlines = lib.scan_chunks(stream, chunks(), collect=not p["done"])
        os.remove(path)
        if p is parts[-1] and not p["done"]:                       # a dump that ends without a newline
            recs += [r for r in (lib.india_record(x) for x in stream.finish()) if r]
        if p["done"]:
            print(f"part {p['key']}: already staged (stream advanced)")
            continue
        try:
            now, inserted = dt.datetime.utcnow(), 0
            for sub in range(0, len(recs), 500):       # small batches: a row is ~16 KB, one request must stay well under the limit
                df = spark.createDataFrame([lib.stage_tuple(r, p["source_file"], p["sha256"], now) for r in recs[sub:sub + 500]],
                                           schema=ROW_SCHEMA).dropDuplicates(["code", "last_modified_t"])
                df.createOrReplaceTempView("incoming_seed")
                inserted += merge_insert_only(f"{STAGE}.bronze_delta_raw", "incoming_seed")
            # rows carrying this part's name are exactly the rows this part inserted (insert-only merge)
            stored = spark.table(f"{STAGE}.bronze_delta_raw").where(f"source_file = '{p['source_file']}'").count()
            if stored != inserted:
                raise RuntimeError(f"stage holds {stored} rows for the part, the merge reported {inserted} inserted")
            add_manifest_row(f"{STAGE}.bronze_manifest", (p["source_file"], p["sha256"], len(recs), len(recs), inserted, now, RUN_ID))
            staged_rows += len(recs)
            staged_parts += 1
            print(f"part {p['key']}: {nlines:,} lines, {len(recs):,} India, {inserted:,} new in the stage")
        except Exception as e:
            problems.append(f"part {p['key']}: {type(e).__name__}: {str(e)[:120]}")
            all_parts_processed = False
            break
    if all_parts_processed and not stream.complete:
        problems.append("the dump stream ended inside a gzip member: the archive is truncated")
    shutil.rmtree("/tmp/seed_parts", ignore_errors=True)
    finish({"mode": "stage", "parts_staged_now": staged_parts, "india_rows_staged_now": staged_rows,
            "stage_rows_total": spark.table(f"{STAGE}.bronze_delta_raw").count(), "problems": len(problems)})

# COMMAND ----------
if MODE == "promote":
    version = contract.load()["version"]
    if version < 3 and not ALLOW_OLD:
        raise RuntimeError(f"silver's contract is version {version}: promote only after the legacy-nutriments mapper (version 3) is live")
    RAW, MAN = f"{BRONZE}.bronze_delta_raw", f"{BRONZE}.bronze_manifest"
    spark.sql(f"CREATE TABLE IF NOT EXISTS {RAW} {RAW_DDL}")
    spark.sql(f"CREATE TABLE IF NOT EXISTS {MAN} {MAN_DDL}")
    already = {r[0] for r in spark.table(MAN).select("file_name").collect()}
    staged = sorted(spark.table(f"{STAGE}.bronze_manifest").collect(), key=lambda r: r["file_name"])
    todo = [r for r in staged if r["file_name"] not in already]
    print(f"{len(staged)} parts staged, {len(already & {r['file_name'] for r in staged})} already promoted, {len(todo)} to promote")
    moved_rows = moved_parts = 0
    for r in todo:
        name = r["file_name"]
        try:
            rows = spark.table(f"{STAGE}.bronze_delta_raw").where(f"source_file = '{name}'")
            n = rows.count()
            if n != r["rows_inserted"]:
                raise RuntimeError(f"stage holds {n} rows for the part, its manifest says {r['rows_inserted']} were inserted")
            rows.createOrReplaceTempView("promote_rows")
            inserted = merge_insert_only(RAW, "promote_rows")
            # the manifest row is the last write, as everywhere in bronze
            add_manifest_row(MAN, (name, r["file_sha256"], r["lines_expected"], r["rows_read"], inserted, dt.datetime.utcnow(), RUN_ID))
            moved_rows += inserted
            moved_parts += 1
            print(f"{name}: {n:,} staged rows, {inserted:,} new in bronze ({n - inserted:,} already there from the deltas)")
        except Exception as e:
            problems.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
    finish({"mode": "promote", "parts_promoted": moved_parts, "rows_added_to_bronze": moved_rows,
            "bronze_rows_total": spark.table(RAW).count(), "problems": len(problems)})

# COMMAND ----------
if MODE == "drop_stage":
    MAN = f"{BRONZE}.bronze_manifest"
    staged = {r[0] for r in spark.table(f"{STAGE}.bronze_manifest").select("file_name").collect()}
    promoted = {r[0] for r in spark.table(MAN).select("file_name").collect()}
    if staged - promoted:
        raise RuntimeError(f"{len(staged - promoted)} staged part(s) are not in the production manifest: not dropping the stage")
    spark.sql(f"DROP SCHEMA IF EXISTS {STAGE} CASCADE")
    finish({"mode": "drop_stage", "dropped": STAGE, "problems": 0})
