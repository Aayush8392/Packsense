# Databricks notebook source
# Export the steward's REVIEW SET: a chosen real slice of the gold staging view (about 180 products whose newest version still carries an error flag
# about the nutrition table, in five groups, India first), passed through the exit function. It is the material for the answer key against which the
# steward is measured (item 22 and 23). Not a fixture: nothing here is committed or compared with DuckDB.
#
# Everything from "2. Every version" to the end is the same code as p4_modelling/notebooks/export_fixture.py (the exit function and the writing); a test
# (p8_steward/tests/test_review_set.py) fails when the two copies differ. Only the selection (section 1) and the widgets are new.
#
# Run once, by the admin, from p8_steward/bootstrap/run_export_review_set.py (git-sourced, one-off); fetch with p8_steward/bootstrap/fetch_review_set.py,
# which writes to the gitignored output/review_set/ and removes the file from the volume. Nothing but names and counts is printed.

# COMMAND ----------
import datetime as dt
import decimal
import json
import os
import re
import sys

from pyspark.sql import functions as F


def find_repo_root():
    """The folder that holds p2_lakehouse/silver_lib and p4_modelling, wherever the git checkout of this run lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isdir(os.path.join(p, "p2_lakehouse", "silver_lib")) and os.path.isdir(os.path.join(p, "p4_modelling", "gold_lib")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p2_lakehouse/silver_lib and p4_modelling/gold_lib; looked from " + repr(starts))


REPO_ROOT = find_repo_root()
sys.path.insert(0, os.path.join(REPO_ROOT, "p2_lakehouse"))
sys.path.insert(0, os.path.join(REPO_ROOT, "p4_modelling"))
from silver_lib import contract, egress, personal  # noqa: E402
from gold_lib import fixture as fixture_lib  # noqa: E402
sys.path.insert(0, os.path.join(REPO_ROOT, "p8_steward"))
import review_set_lib as rsl  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("gold_schema", "workspace.packsense_gold")        # production gold: staging view, history, flag spans
dbutils.widgets.text("bronze_table", "workspace.packsense_bronze.bronze_delta_raw")
dbutils.widgets.text("out_dir", "/Volumes/workspace/packsense_dev/landing/_review_set")

GOLD = dbutils.widgets.get("gold_schema").strip()
BRONZE = dbutils.widgets.get("bronze_table").strip()
OUT_DIR = dbutils.widgets.get("out_dir").strip().rstrip("/")
STG, HIST, SPANS = f"{GOLD}.stg_silver_versions", f"{GOLD}.product_history", f"{GOLD}.product_flag_spans"

spark.conf.set("spark.sql.session.timeZone", "UTC")   # timestamps in the file are UTC, whatever the session says
C = contract.load()

# COMMAND ----------
# 1. The selection. Candidates: products whose newest version still carries an open error flag about the nutrition table; each gets the group of its
# highest-priority flag (review_set_lib.GROUPS) and an India marker (the product ever listed India). The pick is deterministic (md5 of the barcode).
dbutils.widgets.text("exclude_codes", "")           # barcodes to leave out (the six sample products), comma separated
dbutils.widgets.text("limit_per_group", "36")
dbutils.widgets.text("india_per_group", "22")
dbutils.widgets.text("india_only", "0")            # "1": only Indian products are taken (the fresh sealed set)
EXCLUDE = {c.strip() for c in dbutils.widgets.get("exclude_codes").split(",") if c.strip()}
LIMIT_PER_GROUP, INDIA_PER_GROUP = int(dbutils.widgets.get("limit_per_group")), int(dbutils.widgets.get("india_per_group"))
LIMITS = {g: LIMIT_PER_GROUP for g in rsl.ALL_GROUPS}

candidates_sql = f"""
with f as (
    select code, {rsl.group_case_sql('flag')} as r from {SPANS}
    where is_open = 1 and severity = 'error' and flag like '{rsl.PREFIX}%'
),
per as (select code, min(r) as r from f group by code),
ind as (select code, max(case when array_contains(countries_tags, 'en:india') then 1 else 0 end) as india from {STG} group by code)
select per.code, per.r, ind.india, md5(per.code) as h from per inner join ind on ind.code = per.code
"""
candidates = [{"code": r["code"], "group": rsl.group_name(r["r"]), "india": int(r["india"]), "h": r["h"]} for r in spark.sql(candidates_sql).collect()]
print("candidate products with an open nutrition error flag:", len(candidates), "| India:", sum(c["india"] for c in candidates))
picked, pick_report = rsl.choose(candidates, LIMIT_PER_GROUP, INDIA_PER_GROUP, EXCLUDE, india_only=dbutils.widgets.get("india_only") == "1")
cases = {c["code"]: {c["group"]} for c in picked}
codes = sorted(cases)
case_counts = {g: pick_report["per_group"][g]["taken"] for g in rsl.ALL_GROUPS}
print("products selected:", len(codes))
print("per group (taken / India / available):", {g: (v["taken"], v["india"], v["available"]) for g, v in pick_report["per_group"].items()})
short = pick_report["short_groups"]
print("groups with fewer products than the limit:", short or "none")
if not codes:
    raise RuntimeError("nothing selected: is the gold schema right?")

# COMMAND ----------
# 2. Every version of the selected products, from the staging view (no hashed contributor column can be in it).
code_df = spark.createDataFrame([(c,) for c in codes], "code string")
stg = spark.table(STG).join(F.broadcast(code_df), "code", "inner").orderBy("code", "last_modified_t")
columns = {f.name: f.dataType.simpleString() for f in stg.schema.fields}
banned = egress.never_columns(C)
if banned & set(columns):
    raise RuntimeError(f"the staging view carries columns marked egress: never: {sorted(banned & set(columns))}")
rows = [r.asDict(recursive=True) for r in stg.collect()]
print("version rows:", len(rows))

# COMMAND ----------
# 3. The exit function's inputs, built from bronze here and never stored: every contributor name (the global list), and for each
# exported version the names of its OWN contributors, which may stay in `brands` (producers edit their own brand).
SCALARS = ["creator", "last_editor", "last_modified_by", "last_checker", "owner", "owner_imported"]
LISTS = ["editors_tags", "informers_tags", "checkers_tags", "correctors_tags", "photographers_tags", "weighers_tags",
         "editors", "informers", "checkers", "correctors", "photographers", "owners_tags"]
if sorted(SCALARS + LISTS) != sorted(C["personal_source_fields"]):
    raise RuntimeError("the contract's personal_source_fields changed: update the lists in this notebook")

bronze = spark.table(BRONZE)
arrays = [F.array(F.get_json_object("raw_json", f"$.{f}")) for f in SCALARS] + [
    F.coalesce(F.from_json(F.get_json_object("raw_json", f"$.{f}"), "array<string>"), F.array().cast("array<string>")) for f in LISTS]
raw_names = [r["n"] for r in bronze.select(F.explode(F.concat(*arrays)).alias("n")).where("n is not null").distinct().collect()]
NAME_SHAPE = re.compile(r"^[\w.\-]+$")   # all 75,749 names in bronze use only this alphabet (contract note)
handles = {personal.normalise(n) for n in raw_names if isinstance(n, str) and NAME_SHAPE.match(n.strip())}
handles = {h for h in handles if len(h) >= C["egress"]["handle_min_length"]}
print("contributor names of 8+ characters known to the exit function:", len(handles))

wanted = {(r["code"], r["last_modified_t"]) for r in rows}
own = {}
for b in bronze.join(F.broadcast(code_df), "code", "inner").select("code", "last_modified_t", "raw_json").collect():
    key = (b["code"], b["last_modified_t"])
    if key in wanted:
        own[key] = personal.own_handles(json.loads(b["raw_json"]), C["personal_source_fields"], C["own_handle_redaction"]["min_length"])
print("exported versions with a bronze record:", len(own), "of", len(wanted))

# COMMAND ----------
# 4. THE EXIT. Nothing is written before this returns; it raises EgressRefused if anything that must not leave is still present.
handles = fixture_lib.narrow_handles(rows, C, handles)   # only names that occur in the exported text (see gold_lib/fixture.py)
print("of which occur in the exported text:", len(handles))
clean, report = egress.prepare_for_export(rows, C, handles, brand_exempt=own)
print("exit report:", dict(report))
for k in ("product_name", "brands"):
    changed = sum(1 for a, b in zip(rows, clean) if a.get(k) != b.get(k))
    print(f"rows whose {k} the exit changed:", changed)
del handles, own   # the names are not kept anywhere


def to_json_value(v):
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    raise TypeError(f"cannot serialise {type(v).__name__}")


os.makedirs(OUT_DIR, exist_ok=True)
data_path, manifest_path = f"{OUT_DIR}/stg_silver_versions.jsonl", f"{OUT_DIR}/manifest.json"
with open(data_path, "w", encoding="utf-8", newline="\n") as fh:
    for r in sorted(clean, key=lambda x: (x["code"], x["last_modified_t"])):
        fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, default=to_json_value) + "\n")
manifest = {
    "what": "output of the gold staging view stg_silver_versions for a chosen real slice, after the exit function",
    "silver_contract_version": C.get("version"),
    "generated_at_utc": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    "selection_limits": LIMITS,
    "products": len(codes),
    "version_rows": len(rows),
    "cases_per_code": {c: sorted(v) for c, v in sorted(cases.items())},
    "case_counts": case_counts,
    "columns": columns,
    "exit_report": dict(report),
}
with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(manifest, fh, indent=1, sort_keys=True, ensure_ascii=False)
size = os.path.getsize(data_path)
print("written:", data_path, size, "bytes;", manifest_path)

dbutils.notebook.exit(json.dumps({"products": len(codes), "version_rows": len(rows), "bytes": size, "case_counts": case_counts,
                                  "short_cases": short, "exit_report": dict(report)}))
