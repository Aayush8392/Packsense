# Databricks notebook source
# Landing retention: delete landed delta files that are old AND safely stored elsewhere.
#
# The rule (and why) is in p1_intake/retention_lib.py, plain Python and unit-tested on real file names. A file goes only if it is older
# than the retention period (by the end time in its name), bronze loaded it, and the Hugging Face archive holds the same sha256.
# Manifests, taxonomy snapshots and anything that is not an OFF delta file are never touched. Second task of the archive job: it runs
# only if the archive task succeeded, so an archive problem stops deletions. At most `max_deletions` files per run.
# `dry_run` = true only prints the plan. Failures send /fail to the archive healthcheck; success sends nothing (the archive task
# already pinged). Secrets come from the secret scope; none is printed or passed as a parameter.

# COMMAND ----------
# MAGIC %pip install -q huggingface_hub requests

# COMMAND ----------
import datetime as dt
import json
import os
import sys

import requests
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError


def find_p1_intake():
    """The folder that holds retention_lib.py, wherever the git checkout of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "retention_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p1_intake", "retention_lib.py")):
                return os.path.join(p, "p1_intake")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p1_intake/retention_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p1_intake())
import archive_lib  # noqa: E402
import retention_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")          # tests point this at a scratch folder
dbutils.widgets.text("bronze_schema", "workspace.packsense_bronze")
dbutils.widgets.text("hf_repo", "Anonymous8392/packsense-archive")
dbutils.widgets.text("manifest_path", archive_lib.MANIFEST_PATH)
dbutils.widgets.text("retention_days", str(lib.RETENTION_DAYS))
dbutils.widgets.text("max_deletions", str(lib.MAX_DELETIONS))
dbutils.widgets.text("dry_run", "false")                                          # "true" prints the plan and deletes nothing
dbutils.widgets.text("ping_healthchecks", "true")                                 # tests set "false"

RUN_ID = dbutils.widgets.get("run_id")
SCOPE = dbutils.widgets.get("secret_scope")
LANDING = dbutils.widgets.get("landing").rstrip("/")
BRONZE = dbutils.widgets.get("bronze_schema")
HF_REPO = dbutils.widgets.get("hf_repo")
MANIFEST_PATH = dbutils.widgets.get("manifest_path")
RETENTION = int(dbutils.widgets.get("retention_days"))
MAX_DEL = int(dbutils.widgets.get("max_deletions"))
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_archive_ping_url") if PING else None


def ping_fail(body):
    """Best effort: a failing ping must never hide the real error. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + "/fail", data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


def setup():
    """What bronze loaded, what the archive holds, what landing holds. Any failure is reported as /fail and nothing is deleted."""
    deltas = f"{LANDING}/deltas"
    if not os.path.isdir(deltas):
        raise RuntimeError(f"{deltas} does not exist: refusing to run")
    landed = [n for n in os.listdir(deltas) if not os.path.isdir(f"{deltas}/{n}")]
    bronze = {r["file_name"]: r["file_sha256"] for r in spark.table(f"{BRONZE}.bronze_manifest").select("file_name", "file_sha256").collect()}
    api = HfApi(token=dbutils.secrets.get(SCOPE, "hf_archive_token"))
    try:
        path = hf_hub_download(HF_REPO, MANIFEST_PATH, repo_type="dataset", token=api.token, force_download=True)
    except EntryNotFoundError:
        raise RuntimeError("no archive manifest: nothing is archived yet, refusing to delete anything")
    archive = lib.archive_shas(archive_lib.load_manifest(open(path, "rb").read())["files"])
    return deltas, landed, bronze, archive


try:
    deltas, landed, bronze, archive = setup()
except Exception as e:
    ping_fail(f"landing retention setup failed: {type(e).__name__}: {str(e)[:120]}")
    raise

now = dt.datetime.now(dt.timezone.utc)
plan = lib.plan(landed, bronze, archive, now, RETENTION, MAX_DEL)
reasons = {}
for name, why in plan.kept.items():
    reasons[why] = reasons.get(why, 0) + 1
print(f"{len(landed)} files in {deltas}; bronze lists {len(bronze)}, the archive lists {len(archive)} delta files")
print(f"retention {RETENTION} days, cap {MAX_DEL}, dry_run={DRY}")
print(f"keep: {reasons}")
sizes = {n: os.path.getsize(f"{deltas}/{n}") for n in plan.delete}
for n in plan.delete:
    print(f"  {'would delete' if DRY else 'delete'} {n}: {lib.age_days(n, now):.1f} days old, {sizes[n] / 1e6:.1f} MB")

# COMMAND ----------
problems, deleted = [], 0
if not DRY:
    for n in plan.delete:
        try:
            dbutils.fs.rm(f"{deltas}/{n}")
            if os.path.exists(f"{deltas}/{n}"):
                raise RuntimeError("still present after the delete")
            deleted += 1
        except Exception as e:
            problems.append(f"{n}: delete failed: {type(e).__name__}: {str(e)[:120]}")
summary = {"landing": LANDING, "dry_run": DRY, "files_in_landing": len(landed), "eligible": len(plan.delete) + len(plan.deferred),
           "deleted": deleted, "would_delete": len(plan.delete) if DRY else 0, "deferred_by_cap": len(plan.deferred),
           "mb_freed": round(sum(sizes[n] for n in plan.delete) / 1e6, 1) if not DRY else 0, "kept_by_reason": reasons, "problems": len(problems)}
print(json.dumps(summary))
if problems:
    ping_fail("landing retention: " + "; ".join(problems))
    raise RuntimeError("landing retention finished with problems:\n" + "\n".join(problems))
dbutils.notebook.exit(json.dumps(summary))
