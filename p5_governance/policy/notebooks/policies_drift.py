# Databricks notebook source
# Policies drift check: compare policies.yml (row filters, masks, the access table) with what Unity Catalog reports for each table (the same code
# as p5_governance/bootstrap/apply_policies.py check). It runs in the admin-owned policy job. Read-only: nothing is applied. Any missing filter,
# missing mask, wrong access row or missing table raises, which turns the job red.

# COMMAND ----------
import os
import sys


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
            if os.path.isfile(os.path.join(p, "policies.yml")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find policies.yml; looked from " + repr(starts))


ROOT = find_root()
sys.path.insert(0, ROOT)
import grants_lib as gl  # noqa: E402
import policies_lib as pol  # noqa: E402
import policies_live as live  # noqa: E402

dbutils.widgets.text("scope", "packsense_policy")
SCOPE = dbutils.widgets.get("scope").strip()

# COMMAND ----------
from databricks.sdk import WorkspaceClient  # noqa: E402

env = {"DATABRICKS_PIPELINE_TOKEN": dbutils.secrets.get(SCOPE, "pipeline_user_token"),
       "DATABRICKS_ANALYST_TOKEN": dbutils.secrets.get(SCOPE, "analyst_token")}
w = WorkspaceClient()
grants_spec = gl.load_spec(os.path.join(ROOT, "grants.yml"))
spec = pol.load_spec(os.path.join(ROOT, "policies.yml"))
pol.validate(spec, set(grants_spec["principals"]))
result = live.compare(w, spec, grants_spec, env)
text = live.describe(result)
print(text)
if not result["clean"]:
    raise RuntimeError(text)
dbutils.notebook.exit(text)
