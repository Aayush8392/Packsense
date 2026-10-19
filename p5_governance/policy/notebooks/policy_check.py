# Databricks notebook source
# Policy test for one SERVICE PRINCIPAL. The job that runs this notebook runs AS that principal (`run_as`), so every attempt below is made
# with its own rights: no secret of the principal is stored or read anywhere. The notebook refuses to run if the job's identity is not the
# one it was told to test (a mis-set run_as would otherwise test the wrong identity and still pass). Any failed or inconclusive check raises,
# so the job turns red. Output: identities, outcomes and short error classes only.

# COMMAND ----------
import os
import sys


def find_root():
    """The folder holding grants.yml, wherever the deployed copy of this bundle lives."""
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

dbutils.widgets.text("identity", "")      # a role name of grants.yml, e.g. packsense-gold
dbutils.widgets.text("expected_id", "")   # the application (client) id that identity must have: not a secret
IDENTITY = dbutils.widgets.get("identity").strip()
EXPECTED = dbutils.widgets.get("expected_id").strip()

# COMMAND ----------
body = pl.load_checks()["identities"][IDENTITY]
if body["runner"] != "notebook":
    raise RuntimeError(f"{IDENTITY} is tested through the sdk runner, not this notebook")
runner = pr.NotebookRunner(spark, dbutils)
me = runner.whoami()
if me != EXPECTED:
    raise RuntimeError(f"this job runs as a different identity than {IDENTITY}: refusing to test the wrong one")
results = pl.run_checks(body["checks"], runner.attempt_for, runner.cleanup_for)
ok, text = pl.summarise(IDENTITY, results)
print(text)
if not ok:
    raise RuntimeError(text)
dbutils.notebook.exit(text)
