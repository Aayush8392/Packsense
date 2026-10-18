# Databricks notebook source
# Archive: copy every object in the B2 capture bucket (raw/ and taxonomies/) to a private Hugging Face dataset repo.
#
# Why: until this runs, the raw files since 13 Oct exist only in B2 and the landing volume. The Hugging Face copy is the
# independent second copy the design promises. What is copied, and how each file is checked, is decided by
# p1_intake/archive_lib.py (plain Python, unit-tested); this notebook only talks to B2 and Hugging Face.
#
# Per batch of files:
#   1. download from B2 (read-only key) and check each file (size, B2's MD5 ETag, gzip complete, and for a delta file
#      the sha256 the capture recorded); a file that fails a check is NOT uploaded and is reported;
#   2. upload the batch to Hugging Face in one commit, under the same path as its B2 key;
#   3. ask Hugging Face what it stored (sha256 for LFS files, git blob id for small ones) and compare with what we sent;
#   4. only then write the archive manifest (archive/manifest.json), the last write, so a crash leaves a file "not done"
#      and the re-run uploads the same bytes again.
# Nothing is ever deleted from B2. Problems do not stop the other files; the run fails at the end so it goes red and
# healthchecks gets a /fail ping. Secrets come from the secret scope; none is printed or passed as a parameter.

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
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError


def find_p1_intake():
    """The folder that holds archive_lib.py, wherever the git checkout of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "archive_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p1_intake", "archive_lib.py")):
                return os.path.join(p, "p1_intake")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p1_intake/archive_lib.py; looked from " + repr(starts))


P1 = find_p1_intake()
sys.path.insert(0, P1)
import archive_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("b2_endpoint", "https://s3.eu-central-003.backblazeb2.com")   # not a secret (a repo variable)
dbutils.widgets.text("b2_bucket", "packsense-raw-aayush-8392")                      # not a secret (a repo variable)
dbutils.widgets.text("hf_repo", "Anonymous8392/packsense-archive")
dbutils.widgets.text("batch_size", "10")
dbutils.widgets.text("ping_healthchecks", "true")      # tests set "false"
dbutils.widgets.text("only_keys", "")                  # tests: comma-separated B2 keys; empty = everything pending
dbutils.widgets.text("manifest_path", lib.MANIFEST_PATH)  # tests point this at a scratch path
dbutils.widgets.text("dry_run", "false")               # "true": plan only (reads B2 listings and the small capture manifests, downloads and uploads nothing, writes no manifest)

RUN_ID = dbutils.widgets.get("run_id")
SCOPE = dbutils.widgets.get("secret_scope")
BUCKET = dbutils.widgets.get("b2_bucket")
HF_REPO = dbutils.widgets.get("hf_repo")
BATCH = int(dbutils.widgets.get("batch_size"))
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
ONLY = [x.strip() for x in dbutils.widgets.get("only_keys").split(",") if x.strip()]
MANIFEST_PATH = dbutils.widgets.get("manifest_path")
DRY_RUN = dbutils.widgets.get("dry_run").strip().lower() == "true"

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_archive_ping_url") if PING else None


def ping(suffix="", body=None):
    """Best effort: a failing ping must never fail the archive. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=(body or "")[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


ping("/start")
problems = []

def setup():
    """Connect and read what B2 holds and what the archive has. Any failure here is reported to healthchecks as /fail."""
    endpoint = dbutils.widgets.get("b2_endpoint")
    s3 = boto3.client(
        "s3", endpoint_url=endpoint if endpoint.startswith("http") else "https://" + endpoint,
        aws_access_key_id=dbutils.secrets.get(SCOPE, "b2_read_key_id"),
        aws_secret_access_key=dbutils.secrets.get(SCOPE, "b2_read_application_key"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}))
    api = HfApi(token=dbutils.secrets.get(SCOPE, "hf_archive_token"))
    assert api.repo_info(HF_REPO, repo_type="dataset").private, "the archive repo must be private"

    # What B2 holds now (current versions only: a hidden object is not listed) and what the archive already has.
    b2 = {}
    for prefix in lib.ARCHIVE_PREFIXES:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            for o in page.get("Contents", []):
                b2[o["Key"]] = o["Size"]
    print(f"B2 lists {len(b2)} objects under {', '.join(lib.ARCHIVE_PREFIXES)}")

    manifest_lost = False
    try:
        manifest = lib.load_manifest(open(hf_hub_download(HF_REPO, MANIFEST_PATH, repo_type="dataset", token=api.token, force_download=True), "rb").read())
    except EntryNotFoundError:
        manifest = lib.new_manifest()
        manifest_lost = True
        print("no archive manifest found")

    # The sha256 the capture recorded for each delta file: from every capture manifest in B2 (they are archived too).
    capture_manifests = []
    for k in sorted(b2):
        if lib.is_capture_manifest(k):
            capture_manifests.append(json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()))
    expected = lib.expected_sha256(capture_manifests)
    print(f"{len(capture_manifests)} capture manifests read, {len(expected)} files with a recorded sha256")

    if manifest_lost:
        # Guard (adoption A7): without a manifest every B2 key would be downloaded again, which can exceed B2's free daily download cap.
        # Refill the 'done' list from what Hugging Face already holds (path, size and LFS sha256 checked against B2 and the capture record);
        # whatever does not match is archived again as usual. Nothing is downloaded here, and the run is reported as a problem once.
        hf_files = {}
        for item in api.list_repo_tree(HF_REPO, repo_type="dataset", recursive=True, expand=True):
            if getattr(item, "size", None) is not None:
                hf_files[item.path] = {"size": item.size, "sha256": getattr(getattr(item, "lfs", None), "sha256", None)}
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        rebuilt, redo = lib.rebuild_from_listing(manifest, b2, hf_files, expected, RUN_ID, now)
        print(f"manifest rebuilt from the Hugging Face listing: {len(rebuilt)} files taken as archived, {len(redo)} to archive again")
        problems.append(f"the archive manifest was missing: {len(rebuilt)} entries rebuilt from the Hugging Face listing, {len(redo)} files archived again")

    todo, changed = lib.plan(b2, manifest)
    if ONLY:
        todo = [k for k in todo if k in ONLY]
    for k in changed:
        problems.append(f"{k}: size in B2 ({b2[k]}) no longer matches the archived copy ({manifest['files'][k]['bytes']}); not overwritten")
    print(f"{len(manifest['files'])} already archived, {len(todo)} to archive, {len(changed)} changed in B2")
    return s3, api, b2, manifest, todo, changed, expected


try:
    s3, api, b2, manifest, todo, changed, expected = setup()
except Exception as e:
    ping("/fail", f"archive setup failed: {type(e).__name__}: {str(e)[:120]}")
    raise

# COMMAND ----------
if DRY_RUN:
    # Plan only: nothing is downloaded from B2, nothing is uploaded, no manifest is written (a pending ping_healthchecks would still /start).
    plan_out = {"dry_run": True, "b2_objects": len(b2), "already_archived": len(manifest["files"]), "to_archive": len(todo),
                "to_archive_mb": round(sum(b2[k] for k in todo) / 1e6, 1), "size_changed_in_b2": len(changed), "problems": problems}
    print(json.dumps(plan_out))
    dbutils.notebook.exit(json.dumps(plan_out))

# COMMAND ----------
archived, bytes_archived, unverified = 0, 0, 0
for batch in lib.batches(todo, BATCH):
    good = {}  # key -> (data, facts)
    for key in batch:
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=key)
            data = obj["Body"].read()
            problem, facts = lib.check_download(key, data, b2[key], obj["ETag"], expected)
            if problem:
                problems.append(problem)
                print("REFUSED", key)
            else:
                good[key] = (data, facts)
        except Exception as e:
            problems.append(f"{key}: download failed: {type(e).__name__}: {str(e)[:120]}")
            print("FAILED", key, type(e).__name__)
    if not good:
        continue
    try:
        api.create_commit(
            repo_id=HF_REPO, repo_type="dataset", commit_message=f"archive {len(good)} files (run {RUN_ID})",
            operations=[CommitOperationAdd(path_in_repo=k, path_or_fileobj=d) for k, (d, _) in good.items()])
        stored = {i.path: i for i in api.get_paths_info(HF_REPO, list(good), repo_type="dataset", expand=True)}
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for key, (data, facts) in good.items():
            info = stored.get(key)
            lfs = getattr(getattr(info, "lfs", None), "sha256", None) if info else None
            if not info or not lib.hf_matches(facts, data, lfs, getattr(info, "blob_id", None)):
                problems.append(f"{key}: Hugging Face does not report the bytes we sent; not recorded")
                print("MISMATCH", key)
                continue
            lib.record(manifest, key, facts, RUN_ID, now)
            archived += 1
            bytes_archived += facts["bytes"]
            unverified += "none_no_capture_manifest_entry" in facts["checked_against"]
        # the manifest is the last write of the batch
        api.upload_file(path_or_fileobj=lib.dump_manifest(manifest), path_in_repo=MANIFEST_PATH, repo_id=HF_REPO,
                        repo_type="dataset", commit_message=f"archive manifest ({len(manifest['files'])} files, run {RUN_ID})")
        print(f"batch ok: {len(good)} files, {sum(len(d) for d, _ in good.values()) / 1e6:.1f} MB")
    except Exception as e:
        # the message is cut short: it must never carry more than the type and a short reason into the logs
        problems.append(f"batch of {len(good)} files failed: {type(e).__name__}: {str(e)[:120]}")
        print("BATCH FAILED", type(e).__name__)
    del good

# COMMAND ----------
summary = {"b2_objects": len(b2), "archived_before": len(manifest["files"]) - archived, "archived_now": archived,
           "mb_archived_now": round(bytes_archived / 1e6, 1), "delta_files_without_capture_entry": unverified,
           "size_changed_in_b2": len(changed), "problems": len(problems)}
print(json.dumps(summary))
if problems:
    ping("/fail", "archive: " + "; ".join(problems))
    raise RuntimeError("archive finished with problems:\n" + "\n".join(problems))
ping("", json.dumps(summary))
dbutils.notebook.exit(json.dumps(summary))
