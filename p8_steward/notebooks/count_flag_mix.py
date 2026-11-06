# Databricks notebook source
# COUNT ONLY (item 23, decision A121 (k)): the production mix of India nutrition ERROR flags by group, for the weighting of the sealed-test bar.
# Three tables of counts: (1) flags open now, by group; (2) flags by the week they were first seen, split into 'arrived with the product' (first observed
# version) and 'appeared on a product we already held' (a real appearance); (3) the same weekly counts for flags that closed. Every figure is a count of
# flags (spans) and of distinct products: no barcode, no name, no value. A product with two flags in one group counts once in the product column.
# Run by the admin from p8_steward/bootstrap/run_export_review_set.py --notebook count_flag_mix.

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
GOLD = dbutils.widgets.get("gold_schema").strip()
SPANS, STG = f"{GOLD}.product_flag_spans", f"{GOLD}.stg_silver_versions"

# COMMAND ----------
base = f"""
with ind as (select code, max(case when array_contains(countries_tags, 'en:india') then 1 else 0 end) as india from {STG} group by code),
f as (
    select s.code, {rsl.group_case_sql('s.flag')} as r, s.is_open, s.first_seen_is_first_version as arrived,
           date_trunc('week', timestamp_seconds(s.first_seen_t)) as wk
    from {SPANS} s inner join ind on ind.code = s.code and ind.india = 1
    where s.severity = 'error' and s.flag like '{rsl.PREFIX}%'
)
"""
open_now = {rsl.group_name(r["r"]): [int(r["flags"]), int(r["products"])] for r in spark.sql(
    base + "select r, count(*) as flags, count(distinct code) as products from f where is_open = 1 group by r order by r").collect()}
weekly = [{"week": str(r["wk"])[:10], "group": rsl.group_name(r["r"]), "arrived": int(r["arrived"]), "flags": int(r["flags"]), "products": int(r["products"])}
          for r in spark.sql(base + "select wk, r, cast(arrived as int) as arrived, count(*) as flags, count(distinct code) as products "
                             "from f group by wk, r, arrived order by wk, r").collect()]
print("open now (flags, products) by group:", open_now)
print("weekly first-seen rows:", len(weekly))
dbutils.notebook.exit(json.dumps({"open_now": open_now, "weekly": weekly}))
