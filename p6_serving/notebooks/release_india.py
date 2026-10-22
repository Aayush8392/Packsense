# Databricks notebook source
# The India data release (Phase B item 11). Reads the gold mart `mart_india_release`, builds the release folder (exit function with the catalogue-wide
# ordinary words, generated data card and changelog, manifest, licence gate on the rendered files) and, only if the gate passes and dry_run is false, uploads it as ONE
# commit to the PUBLIC Hugging Face dataset named in p6_serving/release_spec.yml, then tags the commit.
#
# Runs as the ADMIN (no run_as; the job is deployed from the laptop): the exit function needs the plaintext contributor names that only bronze holds, and no other
# identity may read them. The names are read into memory, used, and discarded: never written, never printed, never passed on. Prints counts and file names only.
# A gate violation, a refusal by the exit function or a failed upload turns the task red and sends /fail; nothing is uploaded after a violation.
# Widgets: dry_run=true builds and gates the folder but uploads nothing.

# MAGIC %pip install -q huggingface_hub requests pyyaml

# COMMAND ----------
import datetime as dt
import decimal
import json
import os
import re
import sys
import tempfile

import requests


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
            if os.path.isfile(os.path.join(p, "p6_serving", "release_lib.py")) and os.path.isdir(os.path.join(p, "p2_lakehouse", "silver_lib")):
                return p
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p6_serving/release_lib.py and p2_lakehouse/silver_lib; looked from " + repr(starts))


ROOT = find_root()
for sub in ("p6_serving", "p2_lakehouse", "p5_governance"):
    sys.path.insert(0, os.path.join(ROOT, sub))
import release_lib as rl  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402
from silver_lib import contract as silver_contract  # noqa: E402
from silver_lib import personal  # noqa: E402

SPEC = rl.load_spec()
dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("gold_schema", "workspace.packsense_gold")
dbutils.widgets.text("bronze_table", "workspace.packsense_bronze.bronze_delta_raw")
dbutils.widgets.text("hf_repo", SPEC["release"]["hf_repo"])
dbutils.widgets.text("secret_scope", SPEC["release"]["secret_scope"])
dbutils.widgets.text("ping_healthchecks", "true")
dbutils.widgets.text("dry_run", "false")
dbutils.widgets.text("squash_history", "false")   # true: redo the FIRST release (delete the old tags, squash the repo history, no changelog comparison)
GOLD = dbutils.widgets.get("gold_schema").strip()
BRONZE = dbutils.widgets.get("bronze_table").strip()
HF_REPO = dbutils.widgets.get("hf_repo").strip()
SCOPE = dbutils.widgets.get("secret_scope").strip()
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
SQUASH = dbutils.widgets.get("squash_history").strip().lower() == "true"
RUN_ID = dbutils.widgets.get("run_id")
C = silver_contract.load()

ping_url = None
if PING:
    try:
        ping_url = dbutils.secrets.get(SCOPE, "healthchecks_release_ping_url")
    except Exception:
        print("no healthchecks_release_ping_url in the scope: running without a ping")


def ping(suffix, body=""):
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=body[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


def py(v):
    """A Spark value as a plain Python value (numbers may come back as Decimal)."""
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


# COMMAND ----------
try:
    built_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    version = built_at[:10]

    # 1. The mart: one row per India product, only the columns of the release spec.
    rows = [{k: py(v) for k, v in r.asDict().items()} for r in spark.sql(rl.select_sql(SPEC, GOLD)).collect()]
    print("mart rows:", len(rows))
    if not rows:
        raise RuntimeError("the mart is empty: nothing to release")

    # 2. The whole catalogue's text (all markets, the newest period of each product): the base of the ordinary-word count.
    cat = spark.table(f"{GOLD}.product_history").where("is_latest_observed = 1").select("product_name", "brands")
    catalogue = [{"product_name": r["product_name"], "brands": r["brands"]} for r in cat.collect()]
    n_catalogue = len(catalogue)
    print("catalogue products for the ordinary-word count:", n_catalogue)

    # 3. Contributor names from bronze, in memory only (the same fields and filter as the fixture export, p4_modelling/notebooks/export_fixture.py).
    SCALARS = ["creator", "last_editor", "last_modified_by", "last_checker", "owner", "owner_imported"]
    LISTS = ["editors_tags", "informers_tags", "checkers_tags", "correctors_tags", "photographers_tags", "weighers_tags",
             "editors", "informers", "checkers", "correctors", "photographers", "owners_tags"]
    if sorted(SCALARS + LISTS) != sorted(C["personal_source_fields"]):
        raise RuntimeError("the contract's personal_source_fields changed: update the lists in this notebook")
    bronze = spark.table(BRONZE)
    arrays = [F.array(F.get_json_object("raw_json", f"$.{f}")) for f in SCALARS] + [
        F.coalesce(F.from_json(F.get_json_object("raw_json", f"$.{f}"), "array<string>"), F.array().cast("array<string>")) for f in LISTS]
    raw_names = [r["n"] for r in bronze.select(F.explode(F.concat(*arrays)).alias("n")).where("n is not null").distinct().collect()]
    name_shape = re.compile(r"^[\w.\-]+$")
    handles = {personal.normalise(n) for n in raw_names if isinstance(n, str) and name_shape.match(n.strip())}
    handles = {h for h in handles if len(h) >= C["egress"]["handle_min_length"]}
    del raw_names
    print("contributor names of 8+ characters known to the exit function:", len(handles))

    # 4. Ordinary words across the WHOLE catalogue, then the names that can occur in the exported text at all.
    ordinary_extra = rl.catalogue_ordinary_names(catalogue, handles, C)
    del catalogue
    exported_text = [x for r in rows for v in r.values() for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]
    handles = rl.candidate_names(handles, exported_text)
    del exported_text
    print("names ordinary across the catalogue:", len(ordinary_extra), "; names that can occur in the exported text:", len(handles))
    counts = {"mart_rows": len(rows), "catalogue_products": n_catalogue, "ordinary_names": len(ordinary_extra), "candidate_names": len(handles)}

    # 5. Each exported version's OWN contributor names (a producer may stay in its own brand).
    wanted = {(r["code"], r["last_modified_t"]) for r in rows}
    pair_df = spark.createDataFrame([(c, int(t)) for c, t in sorted(wanted)], "code string, last_modified_t bigint")
    own = {}
    for b in bronze.join(F.broadcast(pair_df), ["code", "last_modified_t"], "inner").select("code", "last_modified_t", "raw_json").toLocalIterator():
        own[(b["code"], b["last_modified_t"])] = personal.own_handles(json.loads(b["raw_json"]), C["personal_source_fields"], C["own_handle_redaction"]["min_length"])
    print("exported versions with a bronze record:", len(own), "of", len(wanted))
    counts.update({"versions_with_bronze_record": len(own), "versions_wanted": len(wanted)})

    # 6. The previous release (for the changelog), if there is one.
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi, hf_hub_download
    api = HfApi(token=dbutils.secrets.get(SCOPE, "hf_release_token"))
    previous, previous_version = None, None
    try:
        if SQUASH:
            raise FileNotFoundError("squash_history: this run redoes the first release, so nothing is compared")
        pm = json.load(open(hf_hub_download(HF_REPO, "release_manifest.json", repo_type="dataset", token=api.token), encoding="utf-8"))
        previous_version = pm.get("release_version")
        previous = rl.read_csv_rows(open(hf_hub_download(HF_REPO, SPEC["release"]["data_file"], repo_type="dataset", token=api.token), "rb").read())
        print("previous release:", previous_version, len(previous), "rows")
    except Exception as e:
        print("no previous release found (first release):", type(e).__name__)

    # 7. Build. The exit function and the licence gate raise if anything must not leave; nothing is uploaded then.
    folder = tempfile.mkdtemp(prefix="india_release_")
    manifest = rl.build_release(folder, rows, version, built_at, handles, ordinary_extra, SPEC, brand_exempt=own, previous=previous, previous_version=previous_version)
    del handles, own
    print("gate passed; files:", [(f["path"], f.get("rows")) for f in manifest["files"]])
    print("exit report:", json.dumps(manifest["reports"]))

    if DRY:
        print("dry_run: nothing uploaded")
        summary = f"dry run ok, {len(rows)} products"
    else:
        info = api.repo_info(repo_id=HF_REPO, repo_type="dataset")
        print("target repo is private:", info.private, "(the release is meant to be public)")
        if SQUASH:
            for ref in api.list_repo_refs(repo_id=HF_REPO, repo_type="dataset").tags:
                api.delete_tag(repo_id=HF_REPO, repo_type="dataset", tag=ref.name)
            # empty the repo first, THEN squash: squashing alone would keep the old files in the one remaining commit
            gone = [CommitOperationDelete(path_in_repo=f) for f in api.list_repo_files(repo_id=HF_REPO, repo_type="dataset") if f != ".gitattributes"]
            if gone:
                api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=gone, commit_message="empty the repo before the history is squashed")
            api.super_squash_history(repo_id=HF_REPO, repo_type="dataset")
            print("old files deleted, history squashed and old tags deleted")
        ops = [CommitOperationAdd(path_in_repo=n, path_or_fileobj=os.path.join(folder, n)) for n in sorted(os.listdir(folder))]
        commit = api.create_commit(repo_id=HF_REPO, repo_type="dataset", operations=ops,
                                   commit_message=f"India release {version} (job run {RUN_ID})")
        api.create_tag(repo_id=HF_REPO, repo_type="dataset", tag=f"v{version}", revision=commit.oid, tag_message=f"India release {version}")
        summary = f"published release {version}: {len(rows)} products, {len(ops)} files"
        print(summary)
    counts.update({"summary": summary, "files": [(f["path"], f.get("rows")) for f in manifest["files"]], "exit_report": manifest["reports"]["india_products"]})
    ping("", summary)
except Exception as e:
    ping("/fail", f"{type(e).__name__}: {str(e)[:400]}")
    raise

# COMMAND ----------
# The counts of this run (no name, no product value), returned so that `bundle run` prints them. Kept outside the try: dbutils.notebook.exit raises to leave the notebook.
dbutils.notebook.exit(json.dumps(counts, default=str))
