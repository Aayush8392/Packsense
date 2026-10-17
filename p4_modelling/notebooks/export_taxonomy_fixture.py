# Databricks notebook source
# Export the taxonomy part of the DuckDB comparison fixture: the rows of silver_taxonomy_tag that the committed product fixture uses.
#
# The product fixture (fixtures/stg_silver_versions.jsonl, committed) names countries, labels and quality flags as tags. gold joins those
# to OFF's taxonomies (taxonomy_tag_latest, dim_market, dim_flag), so the fixture needs the taxonomy rows for exactly those tags, plus their
# parents (dim_flag looks the family up through the first parent). Every snapshot of those tags is exported, not only the newest, so the
# "newest snapshot per taxonomy" logic is tested on real data (labels has two snapshots).
#
# The tags come from the committed fixture, which this git-sourced run finds in its own checkout: the selection does not move as silver grows.
# Taxonomy rows hold no contributor data (an allowlist contract), so the exit here is `egress.prepare_vocabulary_for_export`: the scrub
# patterns are applied and the export is refused if a pattern is still found. It runs BEFORE anything is written. Run once, by the admin,
# from `bootstrap/run_export_fixture.py --notebook export_taxonomy_fixture`; `fetch_fixture.py` downloads the result and cleans up.

# COMMAND ----------
import datetime as dt
import decimal
import json
import os
import sys

import yaml
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
    raise RuntimeError("cannot find p2_lakehouse/silver_lib and p4_modelling; looked from " + repr(starts))


REPO_ROOT = find_repo_root()
sys.path.insert(0, os.path.join(REPO_ROOT, "p2_lakehouse"))
from silver_lib import contract, egress  # noqa: E402

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("taxonomy_table", "workspace.packsense_silver.silver_taxonomy_tag")
dbutils.widgets.text("out_dir", "/Volumes/workspace/packsense_dev/landing/_fixture")

TABLE = dbutils.widgets.get("taxonomy_table").strip()
OUT_DIR = dbutils.widgets.get("out_dir").strip().rstrip("/")
S = contract.load()
spark.conf.set("spark.sql.session.timeZone", "UTC")

P4 = os.path.join(REPO_ROOT, "p4_modelling")
GOLD_TAXONOMIES = yaml.safe_load(open(os.path.join(P4, "dbt_project.yml"), encoding="utf-8"))["vars"]["gold_taxonomies"]
FLAG_COLUMNS = ["data_quality_errors_tags", "data_quality_warnings_tags", "data_quality_info_tags", "data_quality_bugs_tags"]
USED_BY = {"countries": ["countries_tags"], "labels": ["labels_tags"], "data_quality": FLAG_COLUMNS,
           "allergens": ["allergens_tags", "traces_tags"], "categories": ["categories_tags"]}
print("taxonomies gold uses:", GOLD_TAXONOMIES)

# COMMAND ----------
# 1. The tags the committed product fixture uses, per taxonomy.
# the product fixture just exported to the volume if it is there (the two exports run back to back), else the committed one
fresh = f"{OUT_DIR}/stg_silver_versions.jsonl"
fixture_path = fresh if os.path.exists(fresh) else os.path.join(P4, "fixtures", "stg_silver_versions.jsonl")
print("product fixture read from:", "the volume (just exported)" if fixture_path == fresh else "the repo checkout")
fixture_rows = [json.loads(line) for line in open(fixture_path, encoding="utf-8")]
wanted = {}
for taxonomy in GOLD_TAXONOMIES:
    if taxonomy not in USED_BY:
        raise RuntimeError(f"no product column is known for the taxonomy {taxonomy}: add it to USED_BY")
    wanted[taxonomy] = {t for r in fixture_rows for col in USED_BY[taxonomy] for t in (r.get(col) or []) if isinstance(t, str)}
print({k: len(v) for k, v in wanted.items()}, "tags used by", len(fixture_rows), "fixture versions")

# Name matches: dim_allergen and dim_market also resolve a tag that is not canonical but equals, ignoring case, exactly one tag's name in some
# language. The canonical tag's row must be in the fixture too, or the fixture could not show the match.
import re  # noqa: E402
for taxonomy in ("allergens", "countries", "categories", "labels"):
    if taxonomy not in wanted:
        continue
    newest = spark.table(TABLE).where(F.col("taxonomy") == taxonomy)
    newest = newest.where(F.col("valid_from") == newest.agg(F.max("valid_from")).collect()[0][0]).collect()
    lookup = {}
    for r in newest:
        for text in (r["names"] or {}).values():
            if isinstance(text, str) and text.strip():
                lookup.setdefault(text.strip().lower(), set()).add(r["tag"])
    known = {r["tag"] for r in newest}
    extra = set()
    for tag in wanted[taxonomy]:
        if tag in known:
            continue
        candidates = lookup.get(re.sub(r"^[^:]*:", "", tag).strip().lower(), set())
        if len(candidates) == 1:
            extra |= candidates
    print(f"{taxonomy}: {len(extra)} canonical tags added for name matches")
    wanted[taxonomy] |= extra

# COMMAND ----------
# 2. Their rows in silver (every snapshot), then the parents' rows.
want_df = spark.createDataFrame([(t, g) for t, tags in wanted.items() for g in sorted(tags)], "taxonomy string, tag string")
first = spark.table(TABLE).join(F.broadcast(want_df), ["taxonomy", "tag"], "inner")
parent_df = first.select("taxonomy", F.explode("parents").alias("tag")).distinct()
second = spark.table(TABLE).join(F.broadcast(parent_df), ["taxonomy", "tag"], "inner")
COLS = ["taxonomy", "tag", "snapshot", "snapshot_sha256", "valid_from", "name_en", "names", "parents", "children", "props"]
result = first.select(*COLS).unionByName(second.select(*COLS)).dropDuplicates(["taxonomy", "snapshot", "tag"]).orderBy("taxonomy", "tag", "valid_from")
columns = {f.name: f.dataType.simpleString() for f in result.schema.fields}
rows = [r.asDict(recursive=True) for r in result.collect()]
matched = {t: sum(1 for r in rows if r["taxonomy"] == t and r["tag"] in wanted[t]) for t in wanted}
print("rows:", len(rows), "| rows for used tags per taxonomy:", matched)
snapshots = {}
for r in rows:
    snapshots.setdefault(r["taxonomy"], set()).add(r["snapshot"])
print("snapshots per taxonomy:", {k: len(v) for k, v in snapshots.items()})

# COMMAND ----------
# 3. THE EXIT. Nothing is written before this returns; it raises EgressRefused if a scrub pattern is still present.
clean, report = egress.prepare_vocabulary_for_export(rows, S)
print("exit report:", dict(report))


def to_json_value(v):
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, decimal.Decimal):
        return float(v)
    raise TypeError(f"cannot serialise {type(v).__name__}")


os.makedirs(OUT_DIR, exist_ok=True)
data_path, manifest_path = f"{OUT_DIR}/taxonomy_tag.jsonl", f"{OUT_DIR}/taxonomy_manifest.json"
with open(data_path, "w", encoding="utf-8", newline="\n") as fh:
    for r in sorted(clean, key=lambda x: (x["taxonomy"], x["tag"], x["valid_from"])):
        fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, default=to_json_value) + "\n")
manifest = {
    "what": "rows of silver_taxonomy_tag for the tags the product fixture uses (countries, labels, quality flags) plus their parents, every snapshot",
    "generated_at_utc": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    "taxonomies": GOLD_TAXONOMIES,
    "version_rows": len(rows),
    "tags_used_per_taxonomy": {k: len(v) for k, v in wanted.items()},
    "snapshots_per_taxonomy": {k: sorted(v) for k, v in snapshots.items()},
    "columns": columns,
    "exit_report": dict(report),
}
with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(manifest, fh, indent=1, sort_keys=True, ensure_ascii=False)
size = os.path.getsize(data_path)
print("written:", data_path, size, "bytes;", manifest_path)
dbutils.notebook.exit(json.dumps({"rows": len(rows), "bytes": size, "matched": matched,
                                  "snapshots": {k: len(v) for k, v in snapshots.items()}, "exit_report": dict(report)}))
