# Databricks notebook source
# The candidate export of the nightly photo-reading job (A123, session 49): India products whose newest silver version still carries an OFF nutrition ERROR flag,
# with their per-100 stored values, written as `input/candidates.json` to the PRIVATE results dataset (the same one the GitHub nightly job reads and writes).
# The rules are in p8_steward/nightly/candidate_export_lib.py (tested); this notebook only runs the query, fetches the previous file and uploads the result.
#
# Runs as the ADMIN (no run_as; deployed from the laptop with p8_steward/nightly_export/): the Hugging Face write token sits in the admin-only scope `packsense_nightly`.
# Prints counts only (no barcode, no value). An empty or shrunk result is refused and the previous file stays; the task turns red and sends /fail.
# Widgets: dry_run=true builds the document and prints the counts but uploads nothing.

# MAGIC %pip install -q huggingface_hub requests

# COMMAND ----------
import datetime as dt
import json
import os
import sys

import requests


def find_dir():
    """The folder that holds `nightly/` (p8_steward in the repo; the bundle may sync it at its own root or under p8_steward/)."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            for cand in (os.path.join(p, "p8_steward"), p):
                if os.path.isfile(os.path.join(cand, "nightly", "candidate_export_lib.py")):
                    return cand
            p = os.path.dirname(p)
    raise RuntimeError("cannot find nightly/candidate_export_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_dir())
from nightly import candidate_export_lib as ce  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("hf_repo", "Anonymous8392/packsense-nightly")
dbutils.widgets.text("secret_scope", "packsense_nightly")
dbutils.widgets.text("ping_healthchecks", "true")
dbutils.widgets.text("dry_run", "false")
HF_REPO = dbutils.widgets.get("hf_repo").strip()
SCOPE = dbutils.widgets.get("secret_scope").strip()
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
PATH = "input/candidates.json"

ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_nightly_export_ping_url")
    except Exception:
        print("no healthchecks_nightly_export_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


# COMMAND ----------
ping("/start")
try:
    exported = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    token = dbutils.secrets.get(SCOPE, "hf_nightly_token")
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
    from huggingface_hub.utils import EntryNotFoundError

    # 1. The previous export (None when the dataset has none yet: the first export marks nobody new).
    previous = None
    try:
        p = hf_hub_download(repo_id=HF_REPO, filename=PATH, repo_type="dataset", token=token, force_download=True)
        previous = json.load(open(p, encoding="utf-8"))
    except EntryNotFoundError:
        print("no previous export in the dataset: this is the first one")

    # 2. The query on silver, then the pure builder (it refuses an empty or shrunk result).
    rows = [r.asDict() for r in spark.sql(ce.candidate_sql()).collect()]
    doc, counts = ce.build_document(rows, previous, exported)
    del rows
    print("counts:", json.dumps(counts, sort_keys=True))

    # 3. One commit with the one file.
    if DRY:
        print("dry_run: nothing uploaded")
    else:
        data = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
        HfApi(token=token).create_commit(repo_id=HF_REPO, repo_type="dataset", operations=[CommitOperationAdd(path_in_repo=PATH, path_or_fileobj=data)],
                                         commit_message=f"candidates export {exported}: {counts['exported']} products, {counts['new']} new")
        print(f"uploaded {PATH} ({len(data)} bytes)")
    ping("", json.dumps({"dry_run": DRY, **counts}, sort_keys=True))
except Exception as e:
    msg = f"{type(e).__name__}: {str(e)[:300]}"
    print("FAILED:", msg)
    ping("/fail", msg)
    raise
