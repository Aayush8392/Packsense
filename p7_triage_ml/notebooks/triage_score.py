# Databricks notebook source
# ruff: noqa: E402  (the pip install and the Python restart come before the imports)
# The weekly scoring of the flag-triage model (P7, roadmap Phase D item 20; design 7.7). The `score` task of the job `packsense-snapshots`, after `open_flags`.
# For the newest finished snapshot it scores every open ERROR flag with each live version of the custom registry (`model_versions`: the newest `production` and the newest
# `measured_reference`), and writes one row per flag and version to `triage_scores` plus one distribution row per version to `triage_score_stats` (the drift check).
# A version is scored with features built the way its own training weeks were (ages count from its first training snapshot). A model file is loaded only if its sha256 is the one
# the registry recorded. Re-running a snapshot replaces its rows. The tables are internal: nothing here is published. Only counts and distribution figures are printed.

# COMMAND ----------
# MAGIC %pip install -q scikit-learn==1.9.1

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import datetime as dt
import json
import os
import sys
import time


def find_p7():
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "triage_model.py")):
                return p
            if os.path.isfile(os.path.join(p, "p7_triage_ml", "triage_model.py")):
                return os.path.join(p, "p7_triage_ml")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p7_triage_ml/triage_model.py; looked from " + repr(starts))


P7 = find_p7()
sys.path.insert(0, P7)
import triage_export as tx  # noqa: E402
import triage_features as tf  # noqa: E402
import triage_model as tm  # noqa: E402

# COMMAND ----------
dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("schema", "workspace.packsense_snapshots")
dbutils.widgets.text("snapshot_date", "")     # empty: the newest snapshot with a finished manifest row
dbutils.widgets.text("dry_run", "false")      # true: score and print the figures, write nothing

SCHEMA = dbutils.widgets.get("schema")
DRY = dbutils.widgets.get("dry_run").strip().lower() == "true"
CONFIG = tm.Config()


def newest_snapshot():
    want = dbutils.widgets.get("snapshot_date").strip()
    if want:
        return want
    row = spark.sql(f"select cast(max(snapshot_date) as string) from {SCHEMA}.snapshot_open_flags_manifest where feature_rows is not null").collect()[0][0]
    if not row:
        raise RuntimeError("no finished snapshot in the manifest")
    return row


def registry_rows():
    cols = ["version", "stage", "recipe_hash", "train_snapshots", "path", "file_sha256", "created_at"]
    return [dict(zip(cols, r)) for r in spark.sql(f"select {', '.join(cols)} from {SCHEMA}.model_versions where model = '{tx.MODEL_NAME}'").collect()]


def flags_for(version_row, snapshot_date):
    """Open error flags of the snapshot with the features of `triage_model.NUMERIC`, built from this version's first training snapshot on."""
    start = tx.from_date_of(version_row)
    flags = f"(select * from {SCHEMA}.snapshot_open_flags where snapshot_date >= DATE'{start}')"
    feats = f"(select * from {SCHEMA}.snapshot_features where snapshot_date >= DATE'{start}')"
    sql = tf.feature_sql(flags=flags, features=feats, engine="spark")
    cols = ["snapshot_sha", "snapshot_date", "code", "severity", "flag", "family", *tm.NUMERIC]
    return spark.sql(f"select * from ({sql}) where severity = '{CONFIG.severity}' and snapshot_date = DATE'{snapshot_date}'").select(*dict.fromkeys(cols)).toPandas()


# COMMAND ----------
def run():
    snapshot = newest_snapshot()
    versions = tx.live_versions(registry_rows())
    print(f"snapshot {snapshot}; versions to score with: {[(v['version'], v['stage']) for v in versions]}", flush=True)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    spark.sql(tx.SCORES_DDL.format(schema=SCHEMA))
    spark.sql(tx.STATS_DDL.format(schema=SCHEMA))
    report = []
    for v in versions:
        t0 = time.time()
        bundle = tx.load_bundle(v["path"], v["file_sha256"])
        df = flags_for(v, snapshot)
        if df.empty:
            raise RuntimeError(f"no open error flags for snapshot {snapshot}: the snapshot's rows are not complete")
        scores = tx.score_frame(bundle, df)
        stats = tx.stats_row(dt.date.fromisoformat(snapshot), v, scores, df["code"].tolist(), tx.missing_shares(df), now)
        report.append({"version": v["version"], "stage": v["stage"], "flags": stats[3], "products": stats[4], "mean": stats[5], "p50": stats[6], "p90": stats[7], "p99": stats[8],
                       "seconds": round(time.time() - t0)})
        print(report[-1], flush=True)
        if DRY:
            continue
        rows = list(zip([dt.date.fromisoformat(snapshot)] * len(df), df["snapshot_sha"], df["code"], df["severity"], df["flag"], df["family"],
                        [int(v["version"])] * len(df), [v["stage"]] * len(df), scores, [now] * len(df)))
        spark.sql(f"delete from {SCHEMA}.triage_scores where snapshot_date = DATE'{snapshot}' and model_version = {int(v['version'])}")
        spark.createDataFrame(rows, "snapshot_date date, snapshot_sha string, code string, severity string, flag string, family string, model_version int, stage string, "
                                    "score double, scored_at timestamp").write.mode("append").saveAsTable(f"{SCHEMA}.triage_scores")
        spark.sql(f"delete from {SCHEMA}.triage_score_stats where snapshot_date = DATE'{snapshot}' and model_version = {int(v['version'])}")
        spark.createDataFrame([stats], "snapshot_date date, model_version int, stage string, n_flags long, n_products long, score_mean double, score_p50 double, score_p90 double, "
                                       "score_p99 double, missing_share string, scored_at timestamp").write.mode("append").saveAsTable(f"{SCHEMA}.triage_score_stats")
        got = spark.sql(f"select count(*) from {SCHEMA}.triage_scores where snapshot_date = DATE'{snapshot}' and model_version = {int(v['version'])}").collect()[0][0]
        if got != len(df):
            raise RuntimeError(f"version {v['version']}: scored {len(df)} flags but the table holds {got}")
    return {"snapshot": snapshot, "dry_run": DRY, "scored": report}


result = run()
text = json.dumps(result, default=str)
print(text[:3000])
dbutils.notebook.exit(text[:100000])
