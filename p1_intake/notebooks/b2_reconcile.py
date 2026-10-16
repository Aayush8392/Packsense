# Databricks notebook source
# B2 reconciliation: does the capture bucket hold exactly what our records say it should?
#
# What is compared, and why, is in p1_intake/reconcile_lib.py (plain Python, unit-tested on real key shapes). This notebook only does
# the reading: it LISTS B2 (raw/ and taxonomies/; a listing is a Class C call, about 1 per 1,000 keys, and nothing is downloaded, so the
# free daily download cap is not touched), reads the capture manifests and taxonomy logs from the landing volume (they are mirrored
# there, so B2 is not read for them), reads the archive manifest from Hugging Face, and reports every difference.
# Third task of the archive job, after the archive task, and it runs even if the archive failed (so a problem can still be reported).
# It writes nothing. Findings send /fail to the archive healthcheck and end the task red. Secrets come from the secret scope.

# COMMAND ----------
# MAGIC %pip install -q boto3 huggingface_hub requests

# COMMAND ----------
import datetime as dt
import json
import os
import sys

import boto3
import requests
from botocore.config import Config
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError


def find_p1_intake():
    """The folder that holds reconcile_lib.py, wherever the git checkout of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "reconcile_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p1_intake", "reconcile_lib.py")):
                return os.path.join(p, "p1_intake")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p1_intake/reconcile_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p1_intake())
import archive_lib  # noqa: E402
import reconcile_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("b2_endpoint", "https://s3.eu-central-003.backblazeb2.com")   # not a secret (a repo variable)
dbutils.widgets.text("b2_bucket", "packsense-raw-aayush-8392")                      # not a secret (a repo variable)
dbutils.widgets.text("hf_repo", "Anonymous8392/packsense-archive")
dbutils.widgets.text("manifest_path", archive_lib.MANIFEST_PATH)
dbutils.widgets.text("ping_healthchecks", "true")                                   # tests set "false"

SCOPE = dbutils.widgets.get("secret_scope")
LANDING = dbutils.widgets.get("landing").rstrip("/")
BUCKET = dbutils.widgets.get("b2_bucket")
HF_REPO = dbutils.widgets.get("hf_repo")
MANIFEST_PATH = dbutils.widgets.get("manifest_path")
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


def read_json_dir(folder):
    """{stamp: parsed json} and {stamp: bytes} for every <stamp>.json in a landing folder (missing folder = empty)."""
    parsed, sizes = {}, {}
    if os.path.isdir(folder):
        for n in sorted(os.listdir(folder)):
            if n.endswith(".json"):
                with open(f"{folder}/{n}", "rb") as fh:
                    parsed[n[:-5]] = json.loads(fh.read())
                sizes[n[:-5]] = os.path.getsize(f"{folder}/{n}")
    return parsed, sizes


def gather():
    endpoint = dbutils.widgets.get("b2_endpoint")
    s3 = boto3.client(
        "s3", endpoint_url=endpoint if endpoint.startswith("http") else "https://" + endpoint,
        aws_access_key_id=dbutils.secrets.get(SCOPE, "b2_read_key_id"),
        aws_secret_access_key=dbutils.secrets.get(SCOPE, "b2_read_application_key"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}))
    b2, calls = {}, 0
    for prefix in archive_lib.ARCHIVE_PREFIXES:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            calls += 1
            for o in page.get("Contents", []):
                b2[o["Key"]] = {"size": o["Size"], "modified": o["LastModified"]}

    capture_manifests, manifest_sizes = read_json_dir(f"{LANDING}/manifests")
    tax_logs, log_sizes = read_json_dir(f"{LANDING}/taxonomies/manifests")
    snapshot_sizes = {}
    for log in tax_logs.values():
        for e in log.get("entries", []):
            p = f"{LANDING}/taxonomies/{e['snapshot']}"
            if os.path.isfile(p):
                snapshot_sizes[e["snapshot"]] = os.path.getsize(p)
    deltas = f"{LANDING}/deltas"
    landing_deltas = {n: os.path.getsize(f"{deltas}/{n}") for n in os.listdir(deltas) if n.endswith(".json.gz")} if os.path.isdir(deltas) else {}

    api = HfApi(token=dbutils.secrets.get(SCOPE, "hf_archive_token"))
    try:
        path = hf_hub_download(HF_REPO, MANIFEST_PATH, repo_type="dataset", token=api.token, force_download=True)
        archive_files = archive_lib.load_manifest(open(path, "rb").read())["files"]
    except EntryNotFoundError:
        archive_files = {}
    return calls, b2, capture_manifests, manifest_sizes, tax_logs, log_sizes, snapshot_sizes, landing_deltas, archive_files


try:
    calls, b2, cm, ms, tl, ls, ss, ld, af = gather()
except Exception as e:      # the message is cut short: it never carries more than the type and a short reason
    ping_fail(f"b2 reconcile could not gather its inputs: {type(e).__name__}: {str(e)[:120]}")
    raise

now = dt.datetime.now(dt.timezone.utc)
findings = lib.reconcile(b2, cm, ms, tl, ls, ss, ld, af, now)
print(f"B2 lists {len(b2)} objects ({calls} listing call(s), no downloads); {len(cm)} capture manifests, {len(tl)} taxonomy logs, "
      f"{len(ld)} landed delta files, {len(af)} archive entries")
for f in findings:
    print(f"FINDING {f.code}: {f.key}: {f.detail}")
text = lib.summary(findings)
print(text)
result = {"b2_objects": len(b2), "listing_calls": calls, "capture_manifests": len(cm), "taxonomy_logs": len(tl), "landed_deltas": len(ld),
          "archive_entries": len(af), "findings": len(findings), "by_code": {c: sum(f.code == c for f in findings) for c in sorted({f.code for f in findings})}}
print(json.dumps(result))
if findings:
    ping_fail(text)
    raise RuntimeError("b2 reconciliation found differences:\n" + "\n".join(f"{f.code} {f.key}: {f.detail}" for f in findings)[:3000])
dbutils.notebook.exit(json.dumps(result))
