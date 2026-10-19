# Databricks notebook source
# Reports the policy job to healthchecks.io (check `packsense-policy`): OK when every upstream task succeeded, /fail with the names of the
# tasks that did not. It runs after all the others (run_if ALL_DONE) and never fails the job itself. The URL is never printed.

# COMMAND ----------
import requests

dbutils.widgets.text("results", "")       # "task=state,task=state", filled from {{tasks.<key>.result_state}} by the job
dbutils.widgets.text("scope", "packsense_policy")
dbutils.widgets.text("ping", "false")
pairs = [p.split("=", 1) for p in dbutils.widgets.get("results").split(",") if "=" in p]
bad = [k for k, v in pairs if v.strip().lower() != "success"]
text = ("all %d policy tasks succeeded" % len(pairs)) if not bad else ("policy tasks not successful: " + ", ".join(bad))
print(text)

if dbutils.widgets.get("ping").strip().lower() == "true":
    url = dbutils.secrets.get(dbutils.widgets.get("scope").strip(), "healthchecks_policy_ping_url")
    try:
        requests.post(url + ("" if not bad else "/fail"), data=text[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)
dbutils.notebook.exit(text)
