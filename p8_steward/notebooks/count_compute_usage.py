# Databricks notebook source
# COUNT ONLY (compute tripwire, roadmap 'the three jobs'): compute DBU per hour from system.billing.usage for the last N days, by SKU group.
# Compute = JOBS_SERVERLESS_COMPUTE + SERVERLESS_SQL_COMPUTE (the two SKUs the 28 Oct lock was measured on); everything else is summed as 'other'.
# Needs the admin (system tables cannot be granted to anyone else on Free Edition). Prints and returns hourly numbers only: no job name, no user.
# Run from p8_steward/bootstrap/run_export_review_set.py --notebook count_compute_usage.

# COMMAND ----------
import json

dbutils.widgets.text("days", "14")
DAYS = int(dbutils.widgets.get("days"))
rows = spark.sql(f"""
select date_trunc('hour', usage_start_time) as h, sku_name, sum(usage_quantity) as dbu
from system.billing.usage
where usage_start_time >= date_sub(current_timestamp(), {DAYS})
group by 1, 2 order by 1, 2
""").collect()
out = {}
for r in rows:
    group = "jobs" if r["sku_name"].endswith("JOBS_SERVERLESS_COMPUTE") or "JOBS_SERVERLESS" in r["sku_name"] else (
        "sql" if "SERVERLESS_SQL" in r["sku_name"] else "other")
    key = str(r["h"])[:13]
    out.setdefault(key, {"jobs": 0.0, "sql": 0.0, "other": 0.0})[group] += float(r["dbu"])
print("hours with usage:", len(out), "newest:", max(out) if out else None)
dbutils.notebook.exit(json.dumps({k: {g: round(v, 3) for g, v in d.items()} for k, d in out.items()}))
