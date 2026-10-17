# Databricks notebook source
# Gold build: runs the dbt project (staging, history, flag spans, dimensions, status) as the gold principal and tests it.
#
# Why a notebook and not the native dbt task: the dbt task's identity on Free Edition is untested, while a notebook running as the
# gold principal that signs dbt in with that principal's OAuth credential (read from its own secret scope) is the path proven in test E1b.
# The job runs as whoever deployed it, so this notebook runs as `packsense-gold` (prod) or `packsense-gold-dev` (dev): each can read
# only two silver tables and write only its own gold schema, and neither can read bronze, quarantine or the scope `packsense`.
#
# Gold is rebuilt in full on every run (history is derived from silver's own versions), so the run is idempotent. A run on stale silver
# gives an identical result, which is why the freshness line is informational: staleness of silver itself is already alerted by the
# `packsense-core` check. `dbt build` runs each model and then its tests; a failing test stops everything that depends on it.
# Healthchecks: its own check `packsense-gold` (ping URL in the scope, prod only).

# COMMAND ----------
import json
import os
import shutil
import sys
import tempfile

import requests


def find_project():
    """The folder holding dbt_project.yml, wherever the deployed copy of this bundle lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "dbt_project.yml")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find dbt_project.yml; looked from " + repr(starts))


PROJECT = find_project()
sys.path.insert(0, PROJECT)
from gold_lib import dbt_run  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("dbt_target", "dev")                       # dev or prod: the dbt profile (gold schema) to use
dbutils.widgets.text("silver_schema", "packsense_dev_silver")   # schema name only (the catalog is workspace)
dbutils.widgets.text("secret_scope", "packsense_gold_dev")
dbutils.widgets.text("http_path", "")                           # the SQL warehouse dbt connects through (not a secret)
dbutils.widgets.text("ping_healthchecks", "false")

RUN_ID = dbutils.widgets.get("run_id")
TARGET = dbt_run.check_target(dbutils.widgets.get("dbt_target").strip())
SILVER = dbutils.widgets.get("silver_schema").strip()
SCOPE = dbutils.widgets.get("secret_scope").strip()
HTTP_PATH = dbutils.widgets.get("http_path").strip()
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
if not HTTP_PATH:
    raise RuntimeError("the job parameter http_path is empty")

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_gold_ping_url") if PING else None


def ping(suffix="", body=None):
    """Best effort: a failing ping must never fail the build. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=(body or "")[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


ping("/start")
try:
    row = spark.sql(f"SELECT count(*) AS files, max(processed_at) AS newest FROM workspace.{SILVER}.silver_manifest").collect()[0]
    newest_file = spark.sql(
        f"SELECT file_name FROM workspace.{SILVER}.silver_manifest ORDER BY processed_at DESC LIMIT 1").collect()
    fresh = dbt_run.freshness_text(row["files"], row["newest"], newest_file[0]["file_name"] if newest_file else None)
except Exception as e:
    ping("/fail", "cannot read the silver manifest: " + type(e).__name__)
    raise
print(fresh)

# COMMAND ----------
# dbt signs in as this principal with its OAuth credential from the scope; nothing is printed.
os.environ["DATABRICKS_HOST"] = "https://" + spark.conf.get("spark.databricks.workspaceUrl")
os.environ["DBT_HTTP_PATH"] = HTTP_PATH
os.environ["DATABRICKS_CLIENT_ID"] = dbutils.secrets.get(SCOPE, "oauth_client_id")
os.environ["DATABRICKS_CLIENT_SECRET"] = dbutils.secrets.get(SCOPE, "oauth_client_secret")
os.environ["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"

# dbt writes next to its project (target folder, logs, partial-parse file): work in a private temp copy, not in the workspace folder
work = tempfile.mkdtemp(prefix="gold_")
project_copy = os.path.join(work, "project")
shutil.copytree(PROJECT, project_copy, ignore=shutil.ignore_patterns("target", "logs", "dbt_packages", "tests", "bootstrap"))
args = dbt_run.build_args(project_copy, TARGET, SILVER, os.path.join(work, "target"), os.path.join(work, "logs"))

from dbt.cli.main import dbtRunner  # noqa: E402

res = dbtRunner().invoke(args)
nodes = []
if res.result is not None and hasattr(res.result, "results"):
    nodes = [(r.node.name, getattr(r.status, "value", r.status)) for r in res.result.results]
summary = dbt_run.summarise(nodes)
text = dbt_run.result_text(summary)
print(text)
shutil.rmtree(work, ignore_errors=True)

# COMMAND ----------
if res.success and summary["ok"]:
    ping("", fresh + " | " + text)
    dbutils.notebook.exit(json.dumps({"run_id": RUN_ID, "target": TARGET, "nodes": summary["total"], "counts": summary["counts"]}))
ping("/fail", text if not res.exception else text + " | " + type(res.exception).__name__)
raise RuntimeError(text if not res.exception else text + f" | dbt exception: {type(res.exception).__name__}")
