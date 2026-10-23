# Databricks notebook source
# Publish the public site data (P6, B0; Phase B of the roadmap). Reads the gold tables listed in p6_serving/export_spec.yml, builds the release folder
# (exit function, small-number suppression, manifest, licence gate on the rendered files) and, only if the gate passes, uploads it to the private Hugging Face
# dataset that the Pages workflow reads. No GitHub token lives in Databricks and no Databricks credential lives in GitHub: the dataset repo is the hand-over.
#
# Runs AS the dedicated principal `packsense-publish` (run_as), which can read the listed gold tables and one secret scope and nothing else.
# Prints counts and file names only. A gate violation or a failed upload turns the task red and sends /fail; nothing is uploaded after a violation.
# Widgets: dry_run=true builds and gates the folder but uploads nothing.

# MAGIC %pip install -q huggingface_hub requests pyyaml

# COMMAND ----------
import datetime as dt
import decimal
import json
import os
import sys
import tempfile

import requests


def find_root():
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "p6_serving", "export_lib.py")) and os.path.isdir(os.path.join(p, "p2_lakehouse", "silver_lib")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p6_serving/export_lib.py and p2_lakehouse/silver_lib; looked from " + repr(starts))


ROOT = find_root()
for sub in ("p6_serving", "p2_lakehouse", "p5_governance"):
    sys.path.insert(0, os.path.join(ROOT, sub))
import export_lib as ex  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("gold_schema", "workspace.packsense_gold")
dbutils.widgets.text("hf_repo", "Anonymous8392/packsense-site-data")
dbutils.widgets.text("secret_scope", "packsense_publish")
dbutils.widgets.text("ping_healthchecks", "true")
dbutils.widgets.text("dry_run", "false")
GOLD = dbutils.widgets.get("gold_schema").strip()
HF_REPO = dbutils.widgets.get("hf_repo").strip()
SCOPE = dbutils.widgets.get("secret_scope").strip()
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
RUN_ID = dbutils.widgets.get("run_id")

ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_publish_ping_url")
    except Exception:
        print("no healthchecks_publish_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


# COMMAND ----------
def py(v):
    """A Spark value as a plain Python value (counts come back as int or Decimal)."""
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


try:
    spec = ex.load_spec()
    datasets = {}
    for name in spec["datasets"]:
        rows = [{k: py(v) for k, v in r.asDict().items()} for r in spark.sql(ex.select_sql(name, spec, GOLD)).collect()]
        datasets[name] = rows
        print(name, "rows read:", len(rows))
    cards = [{k: py(v) for k, v in r.asDict().items()} for r in spark.sql(ex.card_select_sql(spec, GOLD)).collect()]
    print("cards read:", len(cards))

    q = datasets["quality_daily"]
    days = sorted({r["snapshot_date"] for r in q})
    last = days[-1]
    held = {r["scope"]: r["n_products_held"] for r in q if r["snapshot_date"] == last}
    status = {
        "built_at_utc": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        "first_complete_day": ex._clean(days[0]),
        "last_complete_day": ex._clean(last),
        "products_held_all": max(held.values()) if held else 0,
        "products_held_india": held.get("india", 0),
    }
    print("status:", status)

    folder = tempfile.mkdtemp(prefix="site_release_")
    manifest = ex.build_release(folder, datasets, status, spec, cards=cards)      # raises ExportRefused if the licence gate finds anything
    print("gate passed; files:", [(f["path"], f.get("rows")) for f in manifest["files"] if f["kind"] not in ("card", "card_index")])
    print("card shards:", json.dumps(manifest["reports"]["card_shards"]))
    print("reports:", json.dumps(manifest["reports"]))

    if DRY:
        print("dry_run: nothing uploaded")
        summary = "dry run ok"
    else:
        from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
        api = HfApi(token=dbutils.secrets.get(SCOPE, "hf_site_token"))
        names = sorted(os.path.relpath(os.path.join(d, f), folder).replace(os.sep, "/") for d, _, fs in os.walk(folder) for f in fs)
        ops = [CommitOperationAdd(path_in_repo=f"site/{n}", path_or_fileobj=os.path.join(folder, n)) for n in names]
        # shards that no longer exist (a prefix that stopped being split, a barcode range that emptied) are deleted in the same commit
        stale = [f for f in api.list_repo_files(repo_id=HF_REPO, repo_type="dataset") if f.startswith("site/cards/") and f[len("site/"):] not in set(names)]
        ops += [CommitOperationDelete(path_in_repo=f) for f in stale]
        print("files to add:", len(names), "stale card files to delete:", len(stale))
        api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=ops,
                          commit_message=f"site data {status['built_at_utc']} (job run {RUN_ID})")
        summary = f"published {len(names)} files ({len(stale)} stale deleted), built {status['built_at_utc']}"
        print(summary)
    ping("", summary)
except Exception as e:
    ping("/fail", f"{type(e).__name__}: {str(e)[:400]}")
    raise
