# Databricks notebook source
# ruff: noqa: E402  (the pip install and the Python restart come before the imports)
# The flag-triage model run (P7, roadmap Phase D item 17). One notebook, four modes, run by the admin as a one-off from a pushed branch:
#   smoke   a few seconds of the whole path on the weeks that exist, to find API errors; its numbers mean nothing
#   dev     trains on the early training weeks and scores the last training weeks (never the test weeks); repeat as often as needed
#   freeze  writes the configuration, the weeks and the hashes of the code to `triage_runs` and prints the freeze hash; trains nothing
#   final   trains on all training weeks and scores the test weeks ONCE; refuses unless widget freeze_hash equals the hash of the CURRENT code,
#           configuration and weeks, and refuses a second time for the same hash
#   export  trains the model with family ONE more time on chosen weeks, saves the file in a Unity Catalog volume and adds a row to `model_versions` (the custom registry,
#           roadmap item 20). It scores nothing and reads no test week for a measurement. train_weeks is `freeze:<hash prefix>` (the training weeks of that freeze, read from
#           `triage_runs`; refuses unless the four code files are the frozen ones; needs from_date set as it was when the freeze was made) or `all` (every labelled week).
# Only counts and precision figures are printed or stored. Databricks only; no Hugging Face, B2 or LLM is used.

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
import triage_eval as te  # noqa: E402
import triage_export as tx  # noqa: E402
import triage_features as tf  # noqa: E402
import triage_model as tm  # noqa: E402

# COMMAND ----------
dbutils.widgets.text("mode", "smoke")
dbutils.widgets.text("steps", "4")
dbutils.widgets.text("schema", "workspace.packsense_snapshots")
dbutils.widgets.text("freeze_hash", "")
dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("from_date", "")            # smoke only: a start date (the three finished snapshots); export freeze:<hash> needs it too
dbutils.widgets.text("train_weeks", "all")       # export only: all, or freeze:<hash prefix>
dbutils.widgets.text("version", "")              # export only: the registry version to create
dbutils.widgets.text("stage", "")                # export only: measured_reference, production or archived
dbutils.widgets.text("parent_version", "")       # export only: the version this one is a refit of, if any
dbutils.widgets.text("approved_by", "")          # export only: who approved the stage
dbutils.widgets.text("note", "")                 # export only: one sentence for the registry
dbutils.widgets.text("model_dir", "/Volumes/workspace/packsense_snapshots/models")
dbutils.widgets.text("last_week", "")            # freeze and final: ignore labelled weeks after this week number, so the split does not move when newer weeks get their labels

MODE = dbutils.widgets.get("mode")
SCHEMA = dbutils.widgets.get("schema")
RUN_ID = dbutils.widgets.get("run_id")
FREEZE_HASH = dbutils.widgets.get("freeze_hash").strip()
FROM_DATE = dbutils.widgets.get("from_date").strip()
CONFIG = tm.Config(steps=int(dbutils.widgets.get("steps")))
if MODE not in ("smoke", "dev", "freeze", "final", "export"):
    raise ValueError("mode must be smoke, dev, freeze, final or export")

# COMMAND ----------
spark.sql(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.triage_runs (
    run_id STRING, kind STRING, freeze_hash STRING, steps INT, created_at TIMESTAMP, payload STRING) USING DELTA""")


def source(table):
    where = f" where snapshot_date >= DATE'{FROM_DATE}'" if FROM_DATE else ""
    return f"(select * from {SCHEMA}.{table}{where})"


def load_rows():
    """Labelled error flags with their features, one pandas row per open flag, plus the week index (the snapshot's position)."""
    sql = tf.training_sql(CONFIG.steps, flags=source("snapshot_open_flags"), features=source("snapshot_features"),
                          events=f"{SCHEMA}.snapshot_flag_events", presence=f"{SCHEMA}.snapshot_presence_events", engine="spark")
    cols = ["snapshot_date", "code", "severity", "flag", "family", "outcome", "reason", *tm.NUMERIC]
    df = spark.sql(f"select * from ({sql}) where outcome in ('positive','negative') and severity = '{CONFIG.severity}'").select(*cols).toPandas()
    dates = sorted(df["snapshot_date"].unique())
    all_dates = [r[0] for r in spark.sql(f"select distinct snapshot_date from {source('snapshot_open_flags')} order by 1").collect()]
    df["week"] = df["snapshot_date"].map({d: all_dates.index(d) for d in dates})
    return df, all_dates


def run_models(train, test, levels):
    scores = {}
    for name, with_family in (("model_without_family", False), ("model_with_family", True)):
        x_train, y_train = tm.matrix_from_frame(train, with_family, levels)
        x_test, _ = tm.matrix_from_frame(test, with_family, levels)
        t0 = time.time()
        scores[name] = tm.fit_scores(x_train, y_train, x_test, CONFIG, with_family)
        print(f"{name}: trained on {len(train)} rows ({int(y_train.sum())} positives), scored {len(test)} rows in {time.time() - t0:.0f} s", flush=True)
    return scores


def to_rows(df):
    return [{"snapshot_date": str(r.snapshot_date), "code": r.code, "severity": r.severity, "flag": r.flag, "family": r.family, "outcome": r.outcome}
            for r in df.itertuples(index=False)]

def positives_by_week(df):
    return {int(w): int(n) for w, n in df.assign(p=(df["outcome"] == "positive").astype(int)).groupby("week")["p"].sum().items()}


def export_model(df, all_dates):
    """Trains the model with family on the chosen weeks, saves it and registers it. Scores nothing."""
    import sklearn
    version, stage = int(dbutils.widgets.get("version")), dbutils.widgets.get("stage").strip()
    parent = dbutils.widgets.get("parent_version").strip()
    selector = dbutils.widgets.get("train_weeks").strip()
    hashes = tm.code_hashes(P7)
    spark.sql(tx.REGISTRY_DDL.format(schema=SCHEMA))
    if spark.sql(f"select count(*) from {SCHEMA}.model_versions where model = '{tx.MODEL_NAME}' and version = {version}").collect()[0][0]:
        raise RuntimeError(f"version {version} is already in the registry; a version is never overwritten")
    metrics = {"measured": None}
    if selector.startswith("freeze:"):
        if not FROM_DATE:
            raise RuntimeError("export freeze:<hash> needs from_date set as it was at the freeze (the week numbers count from it)")
        prefix = selector.split(":", 1)[1]
        frozen = [json.loads(r[0]) for r in spark.sql(f"select payload from {SCHEMA}.triage_runs where kind = 'freeze' and freeze_hash like '{prefix}%'").collect()]
        if len(frozen) != 1:
            raise RuntimeError(f"expected one freeze record for {prefix!r}, found {len(frozen)}")
        if frozen[0]["code"] != hashes:
            raise RuntimeError("the four code files are not the ones frozen with that hash; restore them (git) before exporting")
        weeks = frozen[0]["weeks"]["train"]
        finals = [json.loads(r[0]) for r in spark.sql(f"select payload from {SCHEMA}.triage_runs where kind = 'final' and freeze_hash like '{prefix}%'").collect()]
        if finals:
            u = finals[0]["report"]["uncovered"]
            metrics = {"measured": {"freeze_hash": frozen[0]["freeze_hash"], "k": u["k"], "uncovered_rows": u["rows"], "uncovered_positives": u["positives"],
                                    "model_with_family": u["systems"].get("model_with_family"), "best_baseline": finals[0]["report"].get("kill_rule")}}
        else:
            raise RuntimeError("that freeze has no final measurement: the measured version is the one that was measured")
    elif selector == "all":
        weeks = sorted(df["week"].unique().tolist())
    else:
        raise ValueError("train_weeks must be all or freeze:<hash prefix>")
    tx.require_positives(positives_by_week(df), weeks)
    train = df[df["week"].isin(weeks)]
    dates = sorted({str(d) for d in train["snapshot_date"].unique()})
    levels = tm.family_levels(to_rows(train))
    x, y = tm.matrix_from_frame(train, True, levels)
    t0 = time.time()
    model, keep = tx.fit_model(x, y, CONFIG, True)
    path = f"{dbutils.widgets.get('model_dir')}/flag_triage_v{version}.joblib"
    digest = tx.save_bundle(path, model, keep, levels, True, CONFIG)
    row = tx.registry_row(version, stage, tx.recipe_hash(CONFIG, dates, hashes), int(parent) if parent else None, dates, len(train), int(y.sum()), CONFIG, hashes,
                          sklearn.__version__, path, digest, tm.jsonable(metrics), dbutils.widgets.get("note"), dbutils.widgets.get("approved_by"),
                          dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    spark.createDataFrame([row], "model string, version int, stage string, recipe_hash string, parent_version int, train_snapshots string, n_train_rows long, n_positives long, "
                                 "config string, code_hashes string, sklearn_version string, path string, file_sha256 string, metrics string, note string, approved_by string, "
                                 "created_at timestamp").write.mode("append").saveAsTable(f"{SCHEMA}.model_versions")
    print(f"trained on {len(train)} rows ({int(y.sum())} positives) from {len(dates)} snapshots in {time.time() - t0:.0f} s; saved {path}", flush=True)
    return {"mode": "export", "version": version, "stage": stage, "weeks": weeks, "snapshots": len(dates), "rows": len(train), "positives": int(y.sum()), "path": path, "sha256": digest}


def run():
    df, all_dates = load_rows()
    if dbutils.widgets.get("last_week").strip():
        df = df[df["week"] <= int(dbutils.widgets.get("last_week"))]
    weeks = sorted(df["week"].unique().tolist())
    print(f"mode {MODE}, window {CONFIG.steps}, {len(df)} labelled error flags over {len(weeks)} weeks of {len(all_dates)} snapshots")
    counts = df.groupby(["week", "outcome"]).size().unstack(fill_value=0)
    print(counts.to_string())
    if MODE == "smoke":
        half = df[df["week"] == weeks[0]]
        levels = tm.family_levels(to_rows(half))
        scores = run_models(half, half, levels)
        rep = tm.evaluate(to_rows(half), scores, min(CONFIG.k, 50))
        return {"mode": "smoke", "rows": len(half), "positives": int((half["outcome"] == "positive").sum()), "ran": sorted(scores), "evaluated": rep["rows"]}
    if MODE == "export":
        return export_model(df, all_dates)
    split = te.split_weeks(weeks, CONFIG.steps, CONFIG.n_test_weeks)
    print("split:", split)
    tx.require_positives(positives_by_week(df), split["train"])
    if MODE == "dev":
        # The test weeks are never read in this mode. The training weeks are cut in half by time; there is NO purge between the halves (with 14 snapshots and
        # a window of 4 the training weeks are too few for one), so this is a sanity run with a fixed configuration, not a tuning loop and not an estimate.
        half = max(1, len(split["train"]) // 2)
        early, late = split["train"][:half], split["train"][half:]
        train = df[df["week"].isin(early)]
        valid = df[df["week"].isin(late)]
        levels = tm.family_levels(to_rows(train))
        scores = run_models(train, valid, levels)
        rep = tm.evaluate(to_rows(valid), scores, CONFIG.k)
        return {"mode": "dev", "early_weeks": early, "late_weeks": late, "purged_between": False, "report": tm.jsonable(rep)}
    record = tm.freeze_record(CONFIG, split, tm.code_hashes(P7))
    if MODE == "freeze":
        spark.createDataFrame([(RUN_ID, "freeze", record["freeze_hash"], CONFIG.steps, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None), json.dumps(record))],
                              "run_id string, kind string, freeze_hash string, steps int, created_at timestamp, payload string") \
            .write.mode("append").saveAsTable(f"{SCHEMA}.triage_runs")
        return {"mode": "freeze", "freeze_hash": record["freeze_hash"], "weeks": record["weeks"], "code": record["code"]}
    # final
    if not FREEZE_HASH or FREEZE_HASH != record["freeze_hash"]:
        raise RuntimeError(f"widget freeze_hash {FREEZE_HASH!r} is not the hash of the current code, configuration and weeks ({record['freeze_hash']}): "
                           "run freeze again, or restore the frozen code")
    finished = [r[0] for r in spark.sql(f"select freeze_hash from {SCHEMA}.triage_runs where kind = 'final'").collect()]
    if not tm.final_allowed(record["freeze_hash"], finished):
        raise RuntimeError("the final measurement for this freeze hash has already been made; it is made once")
    train = df[df["week"].isin(split["train"])]
    test = df[df["week"].isin(split["test"])]
    levels = tm.family_levels(to_rows(train))
    scores = run_models(train, test, levels)
    rep = tm.jsonable(tm.evaluate(to_rows(test), scores, CONFIG.k))
    out = {"mode": "final", "freeze_hash": record["freeze_hash"], "split": split, "report": rep}
    spark.createDataFrame([(RUN_ID, "final", record["freeze_hash"], CONFIG.steps, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None), json.dumps(out))],
                          "run_id string, kind string, freeze_hash string, steps int, created_at timestamp, payload string") \
        .write.mode("append").saveAsTable(f"{SCHEMA}.triage_runs")
    return out


result = run()
text = json.dumps(result, default=str)
print(text[:3000])
dbutils.notebook.exit(text[:100000])
