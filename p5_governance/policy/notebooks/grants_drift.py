# Databricks notebook source
# Grants drift check: compare grants.yml with the live Unity Catalog grants and secret-scope ACLs (the same code as
# p5_governance/bootstrap/apply_grants.py check). It runs in the admin-owned policy job because reading other principals' grants needs
# admin rights: read-only code, nothing is applied or revoked. Any MISSING or EXTRA grant, or a role whose token no longer works, raises.

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
            if os.path.isfile(os.path.join(p, "grants.yml")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find grants.yml; looked from " + repr(starts))


ROOT = find_root()
sys.path.insert(0, ROOT)
import grants_lib as gl  # noqa: E402
import grants_live as live  # noqa: E402

dbutils.widgets.text("scope", "packsense_policy")
SCOPE = dbutils.widgets.get("scope").strip()

# COMMAND ----------
from databricks.sdk import WorkspaceClient  # noqa: E402

# The two users are resolved from their tokens, exactly as on the laptop.
env = {"DATABRICKS_PIPELINE_TOKEN": dbutils.secrets.get(SCOPE, "pipeline_user_token"),
       "DATABRICKS_ANALYST_TOKEN": dbutils.secrets.get(SCOPE, "analyst_token")}
w = WorkspaceClient()
spec = gl.load_spec(os.path.join(ROOT, "grants.yml"))
result = live.compare(w, spec, env)
text = live.describe(result)
print(text)
if not result["clean"]:
    raise RuntimeError(text)
dbutils.notebook.exit(text)
