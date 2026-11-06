# Databricks notebook source
# COUNT ONLY (item 23, fresh sealed set): how many India products had a nutrition error flag that is CLOSED now (a later version dropped it), per flag group,
# leaving out every product already in a review-set part. It reads the gold flag spans and the staging view and prints and returns counts and nothing else:
# no barcode, no name, no value. Run by the admin from p8_steward/bootstrap/run_export_review_set.py --notebook count_closed_flag_pool.

# COMMAND ----------
import json
import os
import sys


def find_repo_root():
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isdir(os.path.join(p, "p8_steward")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p8_steward; looked from " + repr(starts))


sys.path.insert(0, os.path.join(find_repo_root(), "p8_steward"))
import review_set_lib as rsl  # noqa: E402

dbutils.widgets.text("gold_schema", "workspace.packsense_gold")
dbutils.widgets.text("exclude_codes", "")
GOLD = dbutils.widgets.get("gold_schema").strip()
SPANS, STG = f"{GOLD}.product_flag_spans", f"{GOLD}.stg_silver_versions"
EXCLUDE = [c.strip() for c in dbutils.widgets.get("exclude_codes").split(",") if c.strip()]
exclude_df = spark.createDataFrame([(c,) for c in EXCLUDE], "code string")
exclude_df.createOrReplaceTempView("excluded_codes")

# COMMAND ----------
sql = f"""
with f as (
    select code, last_seen_t, {rsl.group_case_sql('flag')} as r from {SPANS}
    where is_open = 0 and severity = 'error' and flag like '{rsl.PREFIX}%'
),
per as (select code, min(r) as r from f group by code),
ind as (select code, max(case when array_contains(countries_tags, 'en:india') then 1 else 0 end) as india from {STG} group by code),
open_now as (select distinct code from {SPANS} where is_open = 1 and severity = 'error' and flag like '{rsl.PREFIX}%')
select per.r as r, count(*) as products
from per
inner join ind on ind.code = per.code and ind.india = 1
left join excluded_codes e on e.code = per.code
left join open_now o on o.code = per.code
where e.code is null and o.code is null
group by per.r order by per.r
"""
counts = {rsl.group_name(r["r"]): int(r["products"]) for r in spark.sql(sql).collect()}
print("India products with a CLOSED nutrition error flag, not in any part and not open now, by group:", counts)
dbutils.notebook.exit(json.dumps({"closed_india_products_by_group": counts, "excluded": len(EXCLUDE)}))
