# Databricks notebook source
# Export the DuckDB comparison fixture: a chosen real slice of the gold staging view, passed through the exit function.
#
# Why this exists: the portable gold models are checked against DuckDB (design 6.6), and DuckDB cannot run the Databricks-only
# staging. So the fixture is the OUTPUT of `stg_silver_versions` for about 250 real products, every version of each, picked to cover
# the cases that matter (one version and many, a no-op pair, a `rev` gap, legacy nutrition, seed-plus-delta overlap, vanishing flags).
# The portable models then run on that file on both engines and must give identical rows.
#
# Run once, by the admin, from the runner `p4_modelling/bootstrap/run_export_fixture.py` (git-sourced, one-off). It reads production
# gold staging, silver's history tables and the plaintext contributor names in bronze (only to build the exit function's name list).
# Every row goes through `silver_lib.egress.prepare_for_export` BEFORE anything is written; the file is then written to the dev landing
# volume (`_fixture/`) and fetched by `fetch_fixture.py`, which also deletes it from the volume. Nothing but names and counts is printed.
#
# The selection is deterministic (ordered by md5 of the barcode, no randomness) for a given silver state; silver grows daily, so a
# later run picks a different slice. That is intended: the fixture is a committed, standing test asset, regenerated only when the
# staging shape changes or a new edge case is wanted.

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

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("gold_schema", "workspace.packsense_gold")        # production gold: staging view, history, flag spans
dbutils.widgets.text("bronze_table", "workspace.packsense_bronze.bronze_delta_raw")
dbutils.widgets.text("out_dir", "/Volumes/workspace/packsense_dev/landing/_fixture")

GOLD = dbutils.widgets.get("gold_schema").strip()
BRONZE = dbutils.widgets.get("bronze_table").strip()
OUT_DIR = dbutils.widgets.get("out_dir").strip().rstrip("/")
STG, HIST, SPANS = f"{GOLD}.stg_silver_versions", f"{GOLD}.product_history", f"{GOLD}.product_flag_spans"

spark.conf.set("spark.sql.session.timeZone", "UTC")   # timestamps in the file are UTC, whatever the session says
C = contract.load()

# COMMAND ----------
# 1. The selection: (barcode, case) pairs. Each case takes the first N barcodes by md5, so the pick is the same for the same silver state.
LIMITS = {
    "versions_1": 20, "versions_2": 30, "versions_3": 20, "versions_4": 5, "versions_5_plus": 25, "most_versions": 3,
    "seed_and_delta": 25, "legacy_nutrition": 15, "india_new_format": 15, "non_india": 15,
    "no_op_pair": 25, "rev_gap": 25, "flag_vanished_with_change": 20, "flag_vanished_untouched": 10,
    "allergen_name_variants": 12, "market_name_variants": 12, "category_name_variants": 12, "label_name_variants": 12,
}

# Real tags observed in production on 2026-10-17 (dim_allergen and dim_market) that are not canonical taxonomy tags but are exactly the
# name of one taxonomy tag in some language, entered under the wrong prefix or in the wrong case. They are what gold's name-match tier
# (dim_allergen.match_type = 'name') resolves; products carrying them keep that logic tested on real data on both engines.
ALLERGEN_VARIANTS = ["en:Milch", "en:lait", "en:Lait", "en:LAIT", "en:Senf", "en:Sellerie", "en:Sesam", "fr:Milch", "en:moutarde",
                     "en:leche", "en:Eier", "en:Œufs", "en:Erdnüsse", "en:céleri", "en:arachides"]
MARKET_VARIANTS = ["en:Türkiye", "en:Nederland", "en:Magyarország", "en:日本", "en:Allemagne", "fr:Francia", "en:Maroc"]
# The same for categories and labels (observed in production 2026-10-17, dim_category and dim_label estimate): Spanish, Dutch and German names
# and singular/plural slips that equal exactly one taxonomy tag's name in some language.
CATEGORY_VARIANTS = ["en:Bebidas", "en:Galletas", "en:Dulces", "en:Yogures", "en:Kaas", "en:Carnes", "en:Leches", "en:chewing-gum", "en:ravioli"]
LABEL_VARIANTS = ["en:kascher", "en:Kascher", "de:Kascher", "en:bio", "de:Vegano", "de:Vegetariano"]

per_code = f"""
select code, count(*) as n,
       max(case when is_seed then 1 else 0 end) as has_seed,
       max(case when not is_seed then 1 else 0 end) as has_delta,
       max(case when nutrition_format = 'legacy' then 1 else 0 end) as legacy,
       max(case when nutrition_format = 'new' then 1 else 0 end) as new_fmt,
       max(case when array_contains(countries_tags, 'en:india') then 1 else 0 end) as india
from {STG} group by code
"""
spark.sql(per_code).createOrReplaceTempView("fx_per_code")


def pick(case, where_sql, source="fx_per_code", order="md5(code)"):
    return f"(select code, '{case}' as fx_case from (select code from {source} where {where_sql} group by code order by {order} limit {LIMITS[case]}))"


parts = [
    pick("versions_1", "n = 1"), pick("versions_2", "n = 2"), pick("versions_3", "n = 3"), pick("versions_4", "n = 4"),
    pick("versions_5_plus", "n >= 5"),
    f"(select code, 'most_versions' as fx_case from fx_per_code order by n desc, md5(code) limit {LIMITS['most_versions']})",
    pick("seed_and_delta", "has_seed = 1 and has_delta = 1"),
    pick("legacy_nutrition", "legacy = 1"),
    pick("india_new_format", "india = 1 and new_fmt = 1"),
    pick("non_india", "india = 0"),
    pick("no_op_pair", "versions_merged > 1", source=HIST),
    pick("rev_gap", "unseen_edits > 0", source=HIST),
    pick("flag_vanished_with_change", "vanished_with_tracked_change = 1", source=SPANS),
    pick("flag_vanished_untouched", "vanished_with_tracked_change = 0", source=SPANS),
    pick("allergen_name_variants",
         f"arrays_overlap(allergens_tags, array({', '.join(repr(t) for t in ALLERGEN_VARIANTS)})) "
         f"or arrays_overlap(traces_tags, array({', '.join(repr(t) for t in ALLERGEN_VARIANTS)}))", source=STG),
    pick("market_name_variants", f"arrays_overlap(countries_tags, array({', '.join(repr(t) for t in MARKET_VARIANTS)}))", source=STG),
    pick("category_name_variants", f"arrays_overlap(categories_tags, array({', '.join(repr(t) for t in CATEGORY_VARIANTS)}))", source=STG),
    pick("label_name_variants", f"arrays_overlap(labels_tags, array({', '.join(repr(t) for t in LABEL_VARIANTS)}))", source=STG),
]
chosen = spark.sql(" union all ".join(parts)).collect()
cases = {}
for r in chosen:
    cases.setdefault(r["code"], set()).add(r["fx_case"])
codes = sorted(cases)
case_counts = {k: sum(1 for v in cases.values() if k in v) for k in LIMITS}
print("products selected:", len(codes))
print("per case:", case_counts)
short = [k for k, n in case_counts.items() if n < LIMITS[k]]
print("cases with fewer products than the limit:", short or "none")
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
