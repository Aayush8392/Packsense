"""Outage (catch-up) drill, P9: the capture kept landing one file a day, but bronze and silver did not run for N days. One pass over the N
files must give exactly what N separate daily runs gave.

What it does (everything in scratch areas; production tables are only read, counts are compared before and after):
  1. picks the latest N days that production has fully loaded into bronze AND silver and that are still in landing;
  2. copies those delta files and all capture manifests, inside Databricks, to landing/_test_outage (no B2, no Hugging Face);
  3. runs the real bronze notebook ONCE over all N files into workspace.ps_outage_bronze, then the real silver notebook ONCE into
     workspace.ps_outage_silver (the notebooks run unchanged from the git branch);
  4. compares both with production for the same files (the checks of crash_test.py) and runs both notebooks a SECOND time: nothing may change;
  5. drops the scratch schemas, removes the copy, compares the production fingerprint, STOPS the SQL warehouse, and prints the cost:
     seconds of each notebook run and the run ids, so the DBU can be read afterwards from system.billing.usage.

  python p2_lakehouse/bootstrap/outage_drill.py plan  --env-file PATH [--days 3]       read only: the files, megabytes, rows for N = 3, 10, 20
  python p2_lakehouse/bootstrap/outage_drill.py run   --env-file PATH --days 3 [--branch main]
  python p2_lakehouse/bootstrap/outage_drill.py usage --env-file PATH --days 3          DBU of the runs of the last `run` (system.billing.usage lags by hours)
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed. The silver run reads the HMAC key from the secret scope as the admin.
"""
import argparse
import base64
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crash_test as ct  # noqa: E402  (the Databricks plumbing and the bronze/silver comparison with production)

OUTAGE_LANDING = ct.LANDING + "/_test_outage"
SCR_BRONZE = "workspace.ps_outage_bronze"
SCR_SILVER = "workspace.ps_outage_silver"
# verify_bronze / verify_silver read these module names
ct.TEST_LANDING, ct.SCR_BRONZE, ct.SCR_SILVER = OUTAGE_LANDING, SCR_BRONZE, SCR_SILVER
def state_file(days: int) -> Path:
    """One state file per day count, so a later run never overwrites the run ids of an earlier one."""
    return Path(tempfile.gettempdir()) / f"packsense_outage_drill_{days}d.json"

DELTA_RE = re.compile(r"^openfoodfacts_products_(\d{9,11})_(\d{9,11})\.json\.gz$")
GAP_TOLERANCE_S = 3600

COPY_NOTEBOOK = '''# Databricks notebook source
import os
dbutils.widgets.text("mode", "copy")
dbutils.widgets.text("src", "")
dbutils.widgets.text("dst", "")
dbutils.widgets.text("files", "")
mode, src, dst = dbutils.widgets.get("mode"), dbutils.widgets.get("src"), dbutils.widgets.get("dst")
files = [f for f in dbutils.widgets.get("files").split(",") if f]
assert dst.endswith("/_test_outage"), "refusing to touch anything but the scratch folder"
if mode == "copy":
    os.makedirs(dst + "/deltas", exist_ok=True)
    os.makedirs(dst + "/manifests", exist_ok=True)
    for f in files:
        dbutils.fs.cp(f"{src}/deltas/{f}", f"{dst}/deltas/{f}")
    for m in os.listdir(f"{src}/manifests"):
        dbutils.fs.cp(f"{src}/manifests/{m}", f"{dst}/manifests/{m}")
    print("copied", len(files), "deltas and", len(os.listdir(dst + "/manifests")), "manifests")
elif mode == "remove":
    dbutils.fs.rm(dst, True)
    print("removed", dst)
'''


# ---- pure logic (unit-tested) ------------------------------------------------------------------------------------------

def end_time(file_name: str):
    """The end of the period a delta file covers (Unix seconds), from its name; None for anything that is not a delta file."""
    m = DELTA_RE.match(file_name)
    return int(m.group(2)) if m else None


def start_time(file_name: str):
    m = DELTA_RE.match(file_name)
    return int(m.group(1)) if m else None


def pick_latest_loaded(landing_names, done_bronze: set, done_silver: set, n: int) -> list:
    """The latest n delta files that are in landing and finished in BOTH production layers, oldest first."""
    ok = [f for f in landing_names if end_time(f) is not None and f in done_bronze and f in done_silver]
    if len(ok) < n:
        raise ValueError(f"need {n} fully loaded delta files in landing, found {len(ok)}")
    return sorted(sorted(ok, key=end_time)[-n:], key=end_time)


def span_days(files: list) -> float:
    return (end_time(files[-1]) - start_time(files[0])) / 86_400


def gaps(files: list) -> list:
    """Pairs of neighbouring files with more than an hour between the end of one and the start of the next (a day that never landed)."""
    ordered = sorted(files, key=end_time)
    return [(a, b) for a, b in zip(ordered, ordered[1:]) if start_time(b) - end_time(a) > GAP_TOLERANCE_S]


def second_pass_problems(before: dict, after: dict) -> list:
    return [f"{k} changed on the second pass: {before[k]} -> {after[k]}" for k in before if before[k] != after.get(k)]


def verdict(bronze_problems: list, silver_problems: list, second_problems: list) -> str:
    parts = [f"bronze: {len(bronze_problems)}" if bronze_problems else "",
             f"silver: {len(silver_problems)}" if silver_problems else "",
             f"second pass: {len(second_problems)}" if second_problems else ""]
    bad = [p for p in parts if p]
    return "PASS" if not bad else "FAIL (" + ", ".join(bad) + " problem(s))"


def estimate_seconds(measured_seconds: float, measured_rows: int, rows: int) -> float:
    """Cost of a bigger pass, scaled by rows from a measured one. A rough guide: fixed start-up time makes small passes look dearer per row."""
    if measured_rows <= 0:
        raise ValueError("no measured rows")
    return measured_seconds * rows / measured_rows


# ---- Databricks side ---------------------------------------------------------------------------------------------------

def fleet(w, q) -> dict:
    sizes = {i.name: i.file_size for i in w.files.list_directory_contents(f"{ct.LANDING}/deltas") if not i.is_directory}
    done_b = {r[0] for r in q.run(f"SELECT file_name FROM {ct.PROD_BRONZE}.bronze_manifest")}
    done_s = {r[0] for r in q.run(f"SELECT file_name FROM {ct.PROD_SILVER}.silver_manifest")}
    return {"sizes": sizes, "done_b": done_b, "done_s": done_s}


def prod_rows(q, files: list) -> int:
    return int(q.one(f"SELECT count(*) FROM {ct.PROD_BRONZE}.bronze_delta_raw WHERE source_file IN ({ct.inlist(files)})"))


def cmd_plan(w, q, args):
    f = fleet(w, q)
    available = [n for n in f["sizes"] if end_time(n) is not None and n in f["done_b"] and n in f["done_s"]]
    print(f"delta files in landing that production has loaded in bronze and silver: {len(available)}")
    for n in (3, 10, 20):
        if len(available) < n:
            print(f"  N={n}: only {len(available)} available")
            continue
        files = pick_latest_loaded(f["sizes"], f["done_b"], f["done_s"], n)
        mb = sum(f["sizes"][x] for x in files) / 1e6
        print(f"  N={n}: {mb:.0f} MB, {prod_rows(q, files)} bronze rows, span {span_days(files):.1f} days, gaps: {len(gaps(files))}")


def run_seconds(r) -> float:
    return ((r.end_time or 0) - (r.start_time or 0)) / 1000


def run_step(w, label, notebook, params, branch, log, workspace=False):
    t0 = time.time()
    waiter = ct.submit(w, f"packsense-outage-{label}", notebook, params, branch, workspace)
    res, r = ct.wait_terminal(w, waiter.run_id)
    text, err = ct.run_output(w, r)
    secs = run_seconds(r)
    log.append({"label": label, "run_id": waiter.run_id, "result": res, "seconds": secs})
    print(f"{label}: {res} in {secs:.0f} s (wall {time.time() - t0:.0f} s) {text[:200]} {err}", flush=True)
    return res, text, err


def counts(q) -> dict:
    t = {"bronze_rows": f"{SCR_BRONZE}.bronze_delta_raw", "bronze_manifest": f"{SCR_BRONZE}.bronze_manifest",
         "silver_rows": f"{SCR_SILVER}.silver_product_versions", "silver_quarantine": f"{SCR_SILVER}.silver_quarantine",
         "silver_manifest": f"{SCR_SILVER}.silver_manifest"}
    return {k: int(q.one(f"SELECT count(*) FROM {v}")) for k, v in t.items()}


def cmd_run(w, q, args):
    before = ct.fingerprint(q)
    f = fleet(w, q)
    files = pick_latest_loaded(f["sizes"], f["done_b"], f["done_s"], args.days)
    rows = prod_rows(q, files)
    mb = sum(f["sizes"][x] for x in files) / 1e6
    print(f"{args.days} days: {mb:.0f} MB, {rows} production bronze rows, span {span_days(files):.1f} days, gaps: {gaps(files) or 'none'}", flush=True)
    started = datetime.now(timezone.utc)
    log, b_problems, s_problems, second = [], [], [], []
    nb = ct.helper_notebook_path(w).replace("crash_test_copy", "outage_drill_helper")
    try:
        from databricks.sdk.service.workspace import ImportFormat, Language
        w.workspace.import_(path=nb, content=base64.b64encode(COPY_NOTEBOOK.encode()).decode(), format=ImportFormat.SOURCE,
                            language=Language.PYTHON, overwrite=True)
        ct.wait_idle(w)
        res, _, err = run_step(w, "copy", nb, {"mode": "copy", "src": ct.LANDING, "dst": OUTAGE_LANDING, "files": ",".join(files)}, args.branch, log, True)
        if res != "SUCCESS":
            b_problems.append(f"copy failed: {err}")
            return 1
        q.run(f"DROP SCHEMA IF EXISTS {SCR_BRONZE} CASCADE")
        q.run(f"DROP SCHEMA IF EXISTS {SCR_SILVER} CASCADE")
        q.run(f"CREATE SCHEMA {SCR_BRONZE}")
        bp = {"landing": OUTAGE_LANDING, "bronze_schema": SCR_BRONZE}
        sp = {"bronze_schema": SCR_BRONZE, "silver_schema": SCR_SILVER, "ping_healthchecks": "false", "only_files": ",".join(files), "bronze_result": "n/a"}

        res, _, err = run_step(w, "bronze-1", ct.BRONZE_NB, {**bp, "run_id": "outage-b1"}, args.branch, log)
        if res != "SUCCESS":
            b_problems.append(f"bronze run ended {res}: {err}")
            return 1
        b_problems += ct.verify_bronze(q, files)
        res, _, err = run_step(w, "silver-1", ct.SILVER_NB, {**sp, "run_id": "outage-s1"}, args.branch, log)
        if res != "SUCCESS":
            s_problems.append(f"silver run ended {res}: {err}")
            return 1
        s_problems += ct.verify_silver(q, files)
        after_first = counts(q)
        print("after one pass over", args.days, "days:", after_first, flush=True)

        # the second pass: the same notebooks again over the same landing folder; nothing may change
        res, _, err = run_step(w, "bronze-2", ct.BRONZE_NB, {**bp, "run_id": "outage-b2"}, args.branch, log)
        res2, _, err2 = run_step(w, "silver-2", ct.SILVER_NB, {**sp, "run_id": "outage-s2"}, args.branch, log)
        if res != "SUCCESS" or res2 != "SUCCESS":
            second.append(f"second pass ended {res} / {res2}: {err} {err2}")
        else:
            second += second_pass_problems(after_first, counts(q))
            b_problems += [f"(after second pass) {p}" for p in ct.verify_bronze(q, files)]
            s_problems += [f"(after second pass) {p}" for p in ct.verify_silver(q, files)]
        return 0
    finally:
        for s in (SCR_BRONZE, SCR_SILVER):
            q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
        if log:
            run_step(w, "remove", nb, {"mode": "remove", "dst": OUTAGE_LANDING}, args.branch, log, True)
        try:
            w.workspace.delete(nb)
        except Exception as e:
            print("helper notebook not deleted:", type(e).__name__)
        after = ct.fingerprint(q)
        left = int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_outage%'") or 0)
        print("production before:", before)
        print("production after: ", after, "(UNCHANGED)" if after == before else "(DIFFERS: check whether a scheduled run happened meanwhile)")
        print("scratch schemas left:", left)
        try:
            for wh in w.warehouses.list():
                w.warehouses.stop(wh.id)
            print("SQL warehouse stop requested")
        except Exception as e:
            print("warehouse not stopped:", type(e).__name__, "(stop it by hand)")
        notebook_seconds = sum(x["seconds"] for x in log)
        print(f"VERDICT: {verdict(b_problems, s_problems, second)}")
        for p in b_problems + s_problems + second:
            print("  problem:", p)
        print(f"COST: {args.days} days, {rows} rows, {len(log)} notebook runs, {notebook_seconds:.0f} s of notebook time in all;"
              f" wall clock {(datetime.now(timezone.utc) - started).total_seconds():.0f} s (the SQL warehouse was awake for that long)")
        state_file(args.days).write_text(json.dumps({"days": args.days, "rows": rows, "started": started.isoformat(), "runs": log,
                                          "notebook_seconds": notebook_seconds, "verdict": verdict(b_problems, s_problems, second)}, indent=1), encoding="utf-8")


def cmd_usage(w, q, args):
    sf = state_file(args.days)
    if not sf.exists():
        sys.exit(f"no state file {sf}: run the drill with --days {args.days} first")
    st = json.loads(sf.read_text(encoding="utf-8"))
    ids = ",".join(str(r["run_id"]) for r in st["runs"])
    rows = q.run(f"SELECT sku_name, round(sum(usage_quantity), 3) FROM system.billing.usage WHERE usage_metadata.job_run_id IN ({ids}) GROUP BY sku_name")
    print("DBU of the drill's notebook runs:", rows or "no rows yet (billing lags by hours)")
    print(f"drill: {st['days']} days, {st['rows']} rows, {st['notebook_seconds']:.0f} s notebook time, verdict {st['verdict']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["plan", "run", "usage"])
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--branch", default="main", help="git branch the notebooks run from")
    args = ap.parse_args()
    ct.load_env_file(args.env_file)
    w = ct.client()
    q = ct.Sql(w)
    return {"plan": cmd_plan, "run": cmd_run, "usage": cmd_usage}[args.command](w, q, args) or 0


if __name__ == "__main__":
    sys.exit(main())
