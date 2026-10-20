"""Soak test for the snapshot comparison loop: does memory or time per pair grow with the number of pairs?

Why it exists: on 2026-10-20 the production run died (out of memory) after 7 of 12 pairs, with the time per pair rising from 554 s to 1,355 s. A
two-pair test could never have shown that. This script reproduces the LOOP, not the network: it downloads two real snapshots once (about 620 MB), keeps
them as local Parquet files on the driver, then runs the loop many times from disk and logs memory and seconds after every iteration.

It runs two variants concurrently as one-off Databricks runs (admin token, `--env-file`), each writing its telemetry to a scratch table as it goes
(so a kill still leaves the numbers): `old` = the loop that died (one DuckDB connection for all pairs, a joined copy of both snapshots per pair; the
old library is passed with --old-lib) and `new` = the current loop (a worker process per pair). A variant passes when the last third of its
iterations is not slower than 1.15 x the first third and its peak memory has not grown by more than 15%.

  python p9_operations/bootstrap/snapshot_soak.py --env-file .env --old-lib <file with the old snapshot_lib.py> [--old-k 8] [--new-k 12]

Nothing is written outside the dev snapshots schema; the scratch tables and the scratch workspace folder are removed at the end.
"""
from __future__ import annotations

import argparse
import base64
import sys
import threading
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SCHEMA = "workspace.packsense_dev_snapshots"
TELEMETRY = f"{SCHEMA}._soak_telemetry"

NOTEBOOK = r'''# Databricks notebook source
# MAGIC %pip install -q duckdb

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import gc, json, os, shutil, subprocess, sys, tempfile, time
import duckdb

MODE = "__MODE__"
K = __K__
SCHEMA = "__SCHEMA__"
_nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
nb_dir = os.path.dirname(_nb if _nb.startswith("/Workspace") else "/Workspace" + _nb)
sys.path.insert(0, nb_dir)
import snapshot_lib as lib
import snapshot_lib_old as old

work = tempfile.mkdtemp(prefix="soak_")
total_mb = lib.mem_total_mb()
spark.sql(f"create table if not exists {SCHEMA}._soak_telemetry (mode string, i int, seconds double, parent_rss_mb double, peak_mb double, duck_mb double, events int, note string)")

def log(i, seconds, parent, peak, duck, events, note=""):
    spark.sql(f"insert into {SCHEMA}._soak_telemetry values ('{MODE}', {i}, {seconds}, {parent}, {peak if peak is not None else 'null'}, {duck if duck is not None else 'null'}, {events}, '{note}')")

# stage 0: two real snapshots (1 Oct and 19 Oct) to local Parquet, once
cs = lib.fetch_commits(pages=4)
A = lib.pick_snapshots(cs, [lib.parse_commit_date("2026-10-01T23:59:59.000Z")])[0]
C = cs[0]
fa, fc = f"{work}/A.parquet", f"{work}/C.parquet"
t0 = time.time()
spec = {"prev": {"sha": A.sha, "cache": fa}, "cur": {"sha": C["id"], "cache": fc}, "out": f"{work}/stage0.json", "memory_limit_mb": int(0.5 * total_mb),
        "temp_dir": f"{work}/spill", "threads": 8, "byte_guard": lib.BYTE_GUARD, "count_prev": False, "count_cur": False}
json.dump(spec, open(f"{work}/stage0.spec.json", "w"))
proc0 = subprocess.run([sys.executable, os.path.join(nb_dir, "snapshot_lib.py"), "worker", f"{work}/stage0.spec.json"], capture_output=True, text=True, timeout=2700)
assert proc0.returncode == 0, proc0.stderr[-500:]
log(-1, round(time.time() - t0, 1), lib.process_rss_mb(), None, None, 0, f"stage0 download; machine {round(total_mb)} MB; disk free {round(shutil.disk_usage(work).free / 1e9, 1)} GB")
files = [fa, fc]

from pyspark.sql import types as T
EV = T.StructType([T.StructField(n, T.StringType()) for n in ("code", "severity", "flag", "family", "event")])

def write_events(events):
    rows = [(e["code"], e["severity"], e["flag"], e["family"], e["event"]) for e in events]
    for j in range(0, len(rows), 20000):
        spark.createDataFrame(rows[j:j + 20000], EV).write.mode("append").saveAsTable(f"{SCHEMA}._soak_events_{MODE}")

if MODE == "old":
    con = duckdb.connect()
    con.execute("SET threads=8")
    con.execute(f"create table p as select * from read_parquet('{files[0]}')")
    for i in range(K):
        t0 = time.time()
        con.execute("drop table if exists n")
        con.execute(f"create table n as select * from read_parquet('{files[(i + 1) % 2]}')")
        res = old.compute_pair(con, "p", "n")
        counts = old.open_counts(con, "n")
        write_events(res["events"])
        con.execute("drop table if exists p")
        con.execute("alter table n rename to p")
        duck = con.execute("select sum(memory_usage_bytes) from duckdb_memory()").fetchone()[0] / 1e6
        rss = lib.process_rss_mb()
        log(i, round(time.time() - t0, 1), rss, None, round(duck), len(res["events"]))
        if rss > 0.75 * total_mb:
            log(i, 0, rss, None, None, 0, "GUARD: stopped before the notebook could be killed")
            break
else:
    for i in range(K):
        t0 = time.time()
        prev, cur = files[i % 2], files[(i + 1) % 2]
        spec = {"prev": {"sha": "x", "local": prev}, "cur": {"sha": "y", "local": cur}, "out": f"{work}/p{i}.json", "memory_limit_mb": int(0.5 * total_mb),
                "temp_dir": f"{work}/spill", "threads": 8, "count_prev": False, "count_cur": i == 0}
        sp = f"{work}/p{i}.spec.json"
        json.dump(spec, open(sp, "w"))
        proc = subprocess.run([sys.executable, os.path.join(nb_dir, "snapshot_lib.py"), "worker", sp], capture_output=True, text=True, timeout=2700)
        if proc.returncode != 0:
            log(i, round(time.time() - t0, 1), lib.process_rss_mb(), None, None, 0, "WORKER FAILED " + str(proc.returncode) + " " + proc.stderr[-200:].replace("'", " "))
            break
        res = json.load(open(spec["out"]))
        write_events(res["events"])
        log(i, round(time.time() - t0, 1), lib.process_rss_mb(), res["peak_rss_mb"], None, len(res["events"]))
shutil.rmtree(work, ignore_errors=True)
dbutils.notebook.exit(json.dumps({"mode": MODE, "done": True}))
'''


def run_variant(w, mode, k, folder, results):
    from databricks.sdk.service import jobs
    nb = NOTEBOOK.replace("__MODE__", mode).replace("__K__", str(k)).replace("__SCHEMA__", SCHEMA)
    from databricks.sdk.service import workspace
    path = f"{folder}/soak_{mode}"
    w.workspace.import_(path=path, format=workspace.ImportFormat.SOURCE, language=workspace.Language.PYTHON,
                        content=base64.b64encode(nb.encode()).decode(), overwrite=True)
    try:
        waiter = w.jobs.submit(run_name=f"packsense-soak-{mode}", tasks=[jobs.SubmitTask(task_key="soak", notebook_task=jobs.NotebookTask(notebook_path=path))])
        print(f"[{mode}] submitted run {waiter.run_id}", flush=True)
        run = waiter.result(timeout=timedelta(minutes=120))
        out = w.jobs.get_run_output(run_id=run.tasks[0].run_id)
        results[mode] = ("ok", out.notebook_output.result if out.notebook_output else None)
    except Exception as e:                                                         # an OOM kill ends here; the telemetry rows are already written
        results[mode] = ("failed", str(e)[:400])


def verdict(rows):
    """rows: [(i, seconds, parent_rss, peak, duck)] without the stage-0 row. Returns (passed, text)."""
    if len(rows) < 6:
        return False, f"only {len(rows)} iterations: not enough to judge"
    third = max(2, len(rows) // 3)
    mean = lambda xs: sum(xs) / len(xs)                                            # noqa: E731
    first, last = rows[:third], rows[-third:]
    t_ratio = mean([r[1] for r in last]) / mean([r[1] for r in first])
    mem = lambda r: max(r[2], r[3] or 0)                                           # noqa: E731  the notebook process, or the worker of that pair
    m_ratio = max(mem(r) for r in last) / max(mem(r) for r in first)
    parent_growth = rows[-1][2] - rows[0][2]
    ok = t_ratio <= 1.15 and m_ratio <= 1.15 and parent_growth <= 300
    return ok, f"time last/first third {t_ratio:.2f}, peak memory last/first third {m_ratio:.2f}, notebook process growth {parent_growth:.0f} MB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--old-lib", required=True, help="a file holding the OLD snapshot_lib.py (git show 1364f5b:p9_operations/snapshot_lib.py)")
    ap.add_argument("--old-k", type=int, default=8)
    ap.add_argument("--new-k", type=int, default=12)
    ap.add_argument("--only", choices=["old", "new"])
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / "p4_modelling" / "bootstrap"))
    from fixture_databricks import client, load_env_file, run_sql
    load_env_file(a.env_file)
    w = client()
    from databricks.sdk.service import workspace
    me = w.current_user.me().user_name
    folder = f"/Users/{me}/packsense_scratch_soak"
    w.workspace.mkdirs(folder)
    for name, src in (("snapshot_lib.py", ROOT / "p9_operations" / "snapshot_lib.py"), ("snapshot_lib_old.py", Path(a.old_lib))):
        w.workspace.import_(path=f"{folder}/{name}", format=workspace.ImportFormat.AUTO, content=base64.b64encode(src.read_bytes()).decode(), overwrite=True)
    run_sql(w, f"drop table if exists {TELEMETRY}")
    results: dict = {}
    todo = [m for m in ("old", "new") if a.only in (None, m)]
    threads = [threading.Thread(target=run_variant, args=(w, m, a.old_k if m == "old" else a.new_k, folder, results)) for m in todo]
    try:
        [t.start() for t in threads]
        [t.join() for t in threads]
        rows = run_sql(w, f"select mode, i, seconds, parent_rss_mb, peak_mb, duck_mb, events, note from {TELEMETRY} order by mode, i").result.data_array or []
        for mode in todo:
            print(f"\n=== {mode}: run {results.get(mode)}")
            mine = [r for r in rows if r[0] == mode]
            for r in mine:
                print(f"  i={r[1]:>3} {float(r[2]):7.1f} s  notebook {float(r[3]):7.0f} MB  worker-peak {r[4]}  duckdb {r[5]}  events {r[6]}  {r[7] or ''}")
            iters = [(int(r[1]), float(r[2]), float(r[3]), None if r[4] is None else float(r[4]), None if r[5] is None else float(r[5])) for r in mine if int(r[1]) >= 0]
            ok, text = verdict(iters)
            print(f"  VERDICT {mode}: {'PASS' if ok else 'FAIL'} - {text}")
    finally:
        for t in ("_soak_telemetry", "_soak_events_old", "_soak_events_new"):
            run_sql(w, f"drop table if exists {SCHEMA}.{t}")
        w.workspace.delete(folder, recursive=True)
        print("\nscratch tables and workspace folder removed")


if __name__ == "__main__":
    main()
