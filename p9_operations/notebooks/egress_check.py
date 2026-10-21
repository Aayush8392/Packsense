# Databricks notebook source
# Monthly egress check (roadmap item M1; full-automation aim, context file A67): can the pipeline still reach every outside service it depends on, from Databricks compute?
#
# One light request to each service in p9_operations/egress_lib.py (OFF's delta index, a taxonomy file and the product API, Hugging Face, B2, PyPI, healthchecks.io), two seconds
# apart. A connection error, a timeout or an unexpected status turns the task red and sends /fail to the healthchecks check with the NAMES of the failing services (no
# secret is used or printed). HTTP 429 counts as reachable. Nothing is written. Why: Databricks' own page says outbound internet can be restricted to trusted domains while
# a test on 2026-10-18 found it open, so this watches something the vendor says can change.

# COMMAND ----------
import json
import os
import sys

import requests


def find_p9():
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "egress_lib.py")):
                return p
            if os.path.isfile(os.path.join(p, "p9_operations", "egress_lib.py")):
                return os.path.join(p, "p9_operations")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p9_operations/egress_lib.py; looked from " + repr(starts))


sys.path.insert(0, find_p9())
import egress_lib as lib  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("ping_healthchecks", "true")          # dev and tests set "false"
SCOPE = dbutils.widgets.get("secret_scope")
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"

# COMMAND ----------
ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_egress_ping_url")
    except Exception:
        print("no healthchecks_egress_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


# COMMAND ----------
ping("/start")
results = lib.check_all()
for r in results:
    print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['service']}: {r['detail']} ({r['seconds']} s)")
text = lib.summary(results)
print(text)
failed = [r for r in results if not r["ok"]]
if failed:
    ping("/fail", text)
    raise RuntimeError(text)
ping("", text)
dbutils.notebook.exit(json.dumps({"services": len(results), "failed": 0}))
