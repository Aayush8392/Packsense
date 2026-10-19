# Databricks notebook source
# Policy test for one USER (the pipeline user or the analyst). A user cannot be a job's run_as, so this notebook signs in with the user's own
# token from the secret scope `packsense_policy` and makes the attempts through the Databricks SDK. It runs in the admin-owned policy job.
# The token is never printed. An expired or revoked token makes the whoami step fail and the job red.

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
sys.path.insert(0, os.path.join(ROOT, "policy"))
import policy_lib as pl  # noqa: E402
import policy_runners as pr  # noqa: E402

dbutils.widgets.text("identity", "")      # pipeline-user or analyst
dbutils.widgets.text("token_key", "")     # the key in scope packsense_policy that holds that user's token
dbutils.widgets.text("scope", "packsense_policy")
IDENTITY = dbutils.widgets.get("identity").strip()
TOKEN_KEY = dbutils.widgets.get("token_key").strip()
SCOPE = dbutils.widgets.get("scope").strip()

# COMMAND ----------
from databricks.sdk import WorkspaceClient  # noqa: E402

body = pl.load_checks()["identities"][IDENTITY]
if body["runner"] != "sdk":
    raise RuntimeError(f"{IDENTITY} is tested in a job run as the principal, not through this notebook")
host = "https://" + spark.conf.get("spark.databricks.workspaceUrl")
w = WorkspaceClient(host=host, token=dbutils.secrets.get(SCOPE, TOKEN_KEY), auth_type="pat")
runner = pr.SdkRunner(w)
runner.whoami()                       # raises when the token is dead; the name is not printed
results = pl.run_checks(body["checks"], runner.attempt_for, runner.cleanup_for)
ok, text = pl.summarise(IDENTITY, results)
print(text)
if not ok:
    raise RuntimeError(text)
dbutils.notebook.exit(text)
