"""Real mid-write kill test for the bronze and silver notebooks (P2 exit gate: crash recovery).

Crash recovery has so far only been simulated (a state faked by hand). This script kills a RUNNING notebook run through the
Jobs API (cancel_run) while it is writing, re-runs it, and compares the result with production for the same files.

Everything happens in scratch areas; production tables are only read (counts are compared before and after):
  landing   /Volumes/workspace/packsense/landing/_test_kill      (3 real delta files + all capture manifests, copied inside Databricks)
  bronze    workspace.ps_kill_bronze   (bronze kill trials), workspace.ps_kill_sbronze (bronze rows seeded for the silver trials)
  silver    workspace.ps_kill_silver
The notebooks themselves run unchanged from the git branch (their widgets already point them at scratch areas).

  python p2_lakehouse/bootstrap/crash_test.py setup   --env-file PATH           pick the mid-sized delta files, copy, seed, fingerprint production
  python p2_lakehouse/bootstrap/crash_test.py bronze  --env-file PATH [--trials 3] [--branch main]
  python p2_lakehouse/bootstrap/crash_test.py silver  --env-file PATH [--trials 3] [--branch main]
  python p2_lakehouse/bootstrap/crash_test.py cleanup --env-file PATH           drop scratch, remove copies, compare the fingerprint
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed. No B2, Hugging Face or secret is touched.
A kill cannot be aimed exactly: each trial records which write window it landed in, and the trial count is the user's budget.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

REPO = "https://github.com/Aayush8392/Packsense"
LANDING = "/Volumes/workspace/packsense/landing"
TEST_LANDING = LANDING + "/_test_kill"
PROD_BRONZE = "workspace.packsense_bronze"
PROD_SILVER = "workspace.packsense_silver"
SCR_BRONZE = "workspace.ps_kill_bronze"
SCR_SBRONZE = "workspace.ps_kill_sbronze"
SCR_SILVER = "workspace.ps_kill_silver"
BRONZE_NB = "p2_lakehouse/notebooks/bronze_load"
SILVER_NB = "p2_lakehouse/notebooks/silver_load"
STATE_FILE = Path(tempfile.gettempdir()) / "packsense_crash_test.json"
# silver columns that legitimately differ between two runs of the same data (run metadata); everything else must be identical
SILVER_RUN_COLUMNS = {"bronze_ingested_at", "silver_contract_version", "silver_processed_at", "job_run_id"}

COPY_NOTEBOOK = '''# Databricks notebook source
import os
dbutils.widgets.text("mode", "copy")
dbutils.widgets.text("src", "")
dbutils.widgets.text("dst", "")
dbutils.widgets.text("files", "")
mode, src, dst = dbutils.widgets.get("mode"), dbutils.widgets.get("src"), dbutils.widgets.get("dst")
files = [f for f in dbutils.widgets.get("files").split(",") if f]
assert dst.endswith("/_test_kill"), "refusing to touch anything but the scratch folder"
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

def pick_files(sizes: dict, n: int = 6) -> list:
    """The n delta files in the middle of the size ranking (not the smallest, not the biggest): a stable, representative choice."""
    names = sorted((k for k in sizes if k.endswith(".json.gz")), key=lambda k: (sizes[k], k))
    if len(names) < n:
        raise ValueError(f"need {n} delta files, found {len(names)}")
    start = (len(names) - n) // 2
    return sorted(names[start:start + n])


def should_kill(mode: str, written: int, recorded: int, total: int) -> bool:
    """Kill rule for a trial. written = files with data in the target tables, recorded = manifest rows, total = files in the run.
    first_write: as soon as any data is visible; later_file: once one file is fully recorded and more are pending."""
    if mode == "first_write":
        return written > 0 and recorded < total
    if mode == "later_file":
        return recorded >= 1 and recorded < total
    if mode == "midway":
        return total // 2 <= recorded < total
    raise ValueError(mode)


def bronze_window(raw_rows: int, recorded_inserts: int, recorded_files: int, total_files: int) -> str:
    """Where in the write order a killed bronze run stopped, from what is left behind."""
    if raw_rows == 0 and recorded_files == 0:
        return "before the first merge"
    if raw_rows > recorded_inserts:
        return "after a merge, before its manifest row (the risky window)"
    if recorded_files < total_files:
        return "between files"
    return "after the last manifest row (nothing left to do)"


def silver_window(files_with_data: set, files_recorded: set, total_files: int) -> str:
    if not files_with_data and not files_recorded:
        return "before the first write"
    if files_with_data - files_recorded:
        return "after silver/quarantine rows, before the manifest row (the risky window)"
    if len(files_recorded) < total_files:
        return "between files"
    return "after the last manifest row (nothing left to do)"


# ---- Databricks plumbing -----------------------------------------------------------------------------------------------

def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def client():
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"])


class Sql:
    def __init__(self, w):
        self.w = w
        wh = next((x for x in w.warehouses.list()), None)
        if wh is None:
            sys.exit("no SQL warehouse found")
        self.wh = wh.id

    def run(self, statement: str, timeout: int = 300):
        from databricks.sdk.service.sql import StatementState
        r = self.w.statement_execution.execute_statement(warehouse_id=self.wh, statement=statement, wait_timeout="30s")
        t0 = time.time()
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.time() - t0 > timeout:
                raise TimeoutError(statement[:80])
            time.sleep(1)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{r.status.state.value}: {(r.status.error.message if r.status.error else '')[:300]}")
        return (r.result.data_array or []) if r.result else []

    def one(self, statement: str):
        rows = self.run(statement)
        return rows[0][0] if rows else None

    def try_one(self, statement: str, default=None):
        try:
            return self.one(statement)
        except Exception:
            return default


def submit(w, name, notebook, params, branch="main", workspace=False):
    from databricks.sdk.service import jobs
    kw = {} if workspace else {"git_source": jobs.GitSource(git_url=REPO, git_provider=jobs.GitProvider.GIT_HUB, git_branch=branch)}
    return w.jobs.submit(
        run_name=name, timeout_seconds=1800,
        tasks=[jobs.SubmitTask(task_key="t", notebook_task=jobs.NotebookTask(
            notebook_path=notebook, source=jobs.Source.WORKSPACE if workspace else jobs.Source.GIT, base_parameters=params))], **kw)


TERMINAL = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}


def run_state(w, run_id):
    r = w.jobs.get_run(run_id)
    life = r.state.life_cycle_state.value if r.state and r.state.life_cycle_state else None
    res = r.state.result_state.value if r.state and r.state.result_state else None
    return life, res, r


def wait_terminal(w, run_id, minutes=30):
    t0 = time.time()
    while True:
        life, res, r = run_state(w, run_id)
        if life in TERMINAL:
            return res or life, r
        if time.time() - t0 > minutes * 60:
            raise TimeoutError(f"run {run_id}")
        time.sleep(3)


def run_output(w, r):
    out = w.jobs.get_run_output(run_id=r.tasks[0].run_id)
    text = out.notebook_output.result if out.notebook_output and out.notebook_output.result else ""
    err = str(out.error)[:600] if out.error else ""
    return text, err


def helper_notebook_path(w):
    return f"/Users/{w.current_user.me().user_name}/packsense_crash_test_copy"


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def load_state():
    if not STATE_FILE.exists():
        sys.exit(f"no state file {STATE_FILE}: run setup first")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def inlist(files):
    return ",".join("'" + f.replace("'", "") + "'" for f in files)


def fingerprint(q: Sql) -> dict:
    t = {"bronze_rows": f"{PROD_BRONZE}.bronze_delta_raw", "bronze_manifest": f"{PROD_BRONZE}.bronze_manifest",
         "silver_rows": f"{PROD_SILVER}.silver_product_versions", "silver_quarantine": f"{PROD_SILVER}.silver_quarantine",
         "silver_manifest": f"{PROD_SILVER}.silver_manifest"}
    return {k: int(q.one(f"SELECT count(*) FROM {v}")) for k, v in t.items()}


# ---- setup / cleanup ---------------------------------------------------------------------------------------------------

def cmd_setup(w, q: Sql, args):
    sizes = {i.name: i.file_size for i in w.files.list_directory_contents(f"{LANDING}/deltas") if not i.is_directory}
    files = pick_files(sizes, args.files_n)
    print("chosen files:", {f: sizes[f] for f in files})
    done_b = int(q.one(f"SELECT count(*) FROM {PROD_BRONZE}.bronze_manifest WHERE file_name IN ({inlist(files)})"))
    done_s = int(q.one(f"SELECT count(*) FROM {PROD_SILVER}.silver_manifest WHERE file_name IN ({inlist(files)})"))
    if done_b != len(files) or done_s != len(files):
        sys.exit(f"these files are not finished in production bronze ({done_b}) and silver ({done_s}): pick again")
    state = {"files": files, "fingerprint": fingerprint(q), "results": {}}
    save_state(state)

    nb = helper_notebook_path(w)
    from databricks.sdk.service.workspace import ImportFormat, Language
    w.workspace.import_(path=nb, content=base64.b64encode(COPY_NOTEBOOK.encode()).decode(), format=ImportFormat.SOURCE,
                        language=Language.PYTHON, overwrite=True)
    waiter = submit(w, "packsense-crash-test-copy", nb, {"mode": "copy", "src": LANDING, "dst": TEST_LANDING, "files": ",".join(files)}, workspace=True)
    res, r = wait_terminal(w, waiter.run_id)
    text, err = run_output(w, r)
    print("copy:", res, err)
    if res != "SUCCESS":
        sys.exit("copy failed")

    # bronze rows for the silver trials: a Delta copy of exactly these files' production rows (no landing, no B2)
    q.run(f"DROP SCHEMA IF EXISTS {SCR_SBRONZE} CASCADE")
    q.run(f"CREATE SCHEMA {SCR_SBRONZE}")
    q.run(f"CREATE TABLE {SCR_SBRONZE}.bronze_delta_raw AS SELECT * FROM {PROD_BRONZE}.bronze_delta_raw WHERE source_file IN ({inlist(files)})")
    q.run(f"CREATE TABLE {SCR_SBRONZE}.bronze_manifest AS SELECT * FROM {PROD_BRONZE}.bronze_manifest WHERE file_name IN ({inlist(files)})")
    print("seeded", SCR_SBRONZE, "rows:", q.one(f"SELECT count(*) FROM {SCR_SBRONZE}.bronze_delta_raw"))
    print("production fingerprint:", state["fingerprint"])


def cmd_cleanup(w, q: Sql, args):
    state = load_state()
    for s in (SCR_BRONZE, SCR_SBRONZE, SCR_SILVER):
        q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    nb = helper_notebook_path(w)
    waiter = submit(w, "packsense-crash-test-remove", nb, {"mode": "remove", "dst": TEST_LANDING}, workspace=True)
    res, r = wait_terminal(w, waiter.run_id)
    print("remove landing copy:", res)
    try:
        w.workspace.delete(nb)
    except Exception as e:
        print("helper notebook not deleted:", type(e).__name__)
    after = fingerprint(q)
    same = after == state["fingerprint"]
    print("production before:", state["fingerprint"])
    print("production after: ", after)
    print("PRODUCTION UNCHANGED" if same else "PRODUCTION DIFFERS (check whether the 09:00 job ran meanwhile)")
    left = int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_kill%'") or 0)
    print("scratch schemas left:", left)


# ---- bronze trials -----------------------------------------------------------------------------------------------------

def bronze_snapshot(q: Sql):
    # the notebook creates its tables after it starts, so either table may not exist yet
    raw = int(q.try_one(f"SELECT count(*) FROM {SCR_BRONZE}.bronze_delta_raw", 0) or 0)
    try:
        rows = q.run(f"SELECT file_name, rows_inserted FROM {SCR_BRONZE}.bronze_manifest")
    except Exception:
        rows = []
    return raw, rows


def verify_bronze(q: Sql, files: list) -> list:
    problems = []
    n_s = int(q.one(f"SELECT count(*) FROM {SCR_BRONZE}.bronze_delta_raw"))
    n_d = int(q.one(f"SELECT count(*) FROM (SELECT DISTINCT code, last_modified_t FROM {SCR_BRONZE}.bronze_delta_raw)"))
    n_p = int(q.one(f"SELECT count(*) FROM {PROD_BRONZE}.bronze_delta_raw WHERE source_file IN ({inlist(files)})"))
    if n_s != n_d:
        problems.append(f"duplicate keys: {n_s} rows, {n_d} distinct")
    if n_s != n_p:
        problems.append(f"row count {n_s} differs from production {n_p}")
    mism = int(q.one(f"""SELECT count(*) FROM
        (SELECT code, last_modified_t, md5(concat_ws('|', source_file, file_sha256, raw_json)) h FROM {SCR_BRONZE}.bronze_delta_raw) s
        FULL OUTER JOIN (SELECT code, last_modified_t, md5(concat_ws('|', source_file, file_sha256, raw_json)) h
                         FROM {PROD_BRONZE}.bronze_delta_raw WHERE source_file IN ({inlist(files)})) p
        ON s.code <=> p.code AND s.last_modified_t <=> p.last_modified_t
        WHERE s.h IS NULL OR p.h IS NULL OR s.h <> p.h"""))
    if mism:
        problems.append(f"{mism} rows missing, extra or different against production")
    man = q.run(f"SELECT file_name, rows_read, lines_expected FROM {SCR_BRONZE}.bronze_manifest")
    names = sorted(r[0] for r in man)
    if names != sorted(files):
        problems.append(f"manifest rows {names} are not exactly one per file")
    for r in man:
        if r[1] != r[2]:
            problems.append(f"{r[0]}: rows_read {r[1]} != lines_expected {r[2]}")
    return problems


def trial_loop(w, q, run_id, mode, total, snapshot):
    """Poll a running notebook and cancel it when the kill rule fires. Returns (killed, state_after)."""
    t0 = time.time()
    try:
        while True:
            life, res, r = run_state(w, run_id)
            if life in TERMINAL:
                return False, None, None
            written, recorded = snapshot()
            if should_kill(mode, written, recorded, total):
                t_cancel = time.time()
                w.jobs.cancel_run(run_id)
                wait_terminal(w, run_id, 10)
                secs = round(time.time() - t_cancel, 1)
                time.sleep(8)  # let any in-flight write settle before looking at what is left behind
                # what the poll saw when it decided to kill, and how long the cancel took to take effect
                return True, snapshot(), {"seen_at_cancel": [written, recorded], "cancel_seconds": secs}
            if time.time() - t0 > 20 * 60:
                w.jobs.cancel_run(run_id)
                return False, None, None
            time.sleep(1)
    except Exception:
        # never leave a run going if the driver itself fails
        try:
            w.jobs.cancel_run(run_id)
        except Exception:
            pass
        raise


def wait_idle(w):
    """Do not start while an earlier kill-test run (for example one orphaned by a crashed driver) is still active."""
    while True:
        active = [r for r in w.jobs.list_runs(active_only=True) if (r.run_name or "").startswith("packsense-kill-")]
        if not active:
            return
        print(f"waiting for {len(active)} earlier kill-test run(s) to finish: {[r.run_name for r in active]}", flush=True)
        time.sleep(15)


def cmd_bronze(w, q: Sql, args):
    wait_idle(w)
    state = load_state()
    files = state["files"]
    modes = ["first_write", "midway", "later_file", "first_write", "midway", "later_file"]
    out = []
    for i in range(args.trials):
        mode = modes[i % len(modes)]
        q.run(f"DROP SCHEMA IF EXISTS {SCR_BRONZE} CASCADE")
        q.run(f"CREATE SCHEMA {SCR_BRONZE}")
        params = {"landing": TEST_LANDING, "bronze_schema": SCR_BRONZE}
        waiter = submit(w, f"packsense-kill-bronze-{i + 1}", BRONZE_NB, {**params, "run_id": f"kill-b-{i + 1}"}, args.branch)

        def snap():
            raw, rows = bronze_snapshot(q)
            return raw, rows
        killed, after, timing = trial_loop(w, q, waiter.run_id, mode, len(files), lambda: (lambda s: (s[0], len(s[1])))(snap()))
        rec = {"trial": i + 1, "mode": mode, "killed": killed}
        if timing:
            rec.update(timing)
        if killed:
            raw, rows = bronze_snapshot(q)
            ins = sum(int(r[1]) for r in rows)
            rec.update(raw_rows_after_kill=raw, manifest_rows_after_kill=len(rows),
                       window=bronze_window(raw, ins, len(rows), len(files)))
            life, res, _ = run_state(w, waiter.run_id)
            rec["killed_run_state"] = res or life
        else:
            rec["note"] = "the run finished before the kill rule fired: not a kill trial"
        print(f"trial {i + 1}: {rec}", flush=True)
        rw = submit(w, f"packsense-kill-bronze-{i + 1}-recover", BRONZE_NB, {**params, "run_id": f"kill-b-{i + 1}-recover"}, args.branch)
        res, r = wait_terminal(w, rw.run_id)
        text, err = run_output(w, r)
        rec.update(recovery_state=res, recovery_output=text, recovery_error=err)
        rec["problems"] = verify_bronze(q, files) if res == "SUCCESS" else [f"recovery run ended {res}: {err}"]
        print(f"   recovery: {res} {text} -> problems: {rec['problems'] or 'none'}", flush=True)
        out.append(rec)
    state["results"]["bronze"] = out
    save_state(state)


# ---- silver trials -----------------------------------------------------------------------------------------------------

def silver_snapshot(q: Sql):
    t = f"{SCR_SILVER}.silver_product_versions"
    try:
        with_data = {r[0] for r in q.run(f"SELECT DISTINCT source_file FROM {t} UNION SELECT DISTINCT source_file FROM {SCR_SILVER}.silver_quarantine")}
    except Exception:
        with_data = set()
    try:
        recorded = {r[0] for r in q.run(f"SELECT file_name FROM {SCR_SILVER}.silver_manifest")}
    except Exception:
        recorded = set()
    return with_data, recorded


def verify_silver(q: Sql, files: list) -> list:
    problems = []
    cols = [r[0] for r in q.run(f"DESCRIBE TABLE {SCR_SILVER}.silver_product_versions") if r[0] and not r[0].startswith("#")]
    cols = [c for c in cols if c not in SILVER_RUN_COLUMNS]
    h = "md5(to_json(struct(" + ", ".join(cols) + ")))"
    T, P = f"{SCR_SILVER}.silver_product_versions", f"{PROD_SILVER}.silver_product_versions"
    n_s = int(q.one(f"SELECT count(*) FROM {T}"))
    n_d = int(q.one(f"SELECT count(*) FROM (SELECT DISTINCT code, last_modified_t FROM {T})"))
    n_p = int(q.one(f"SELECT count(*) FROM {P} WHERE source_file IN ({inlist(files)})"))
    if n_s != n_d:
        problems.append(f"duplicate keys: {n_s} rows, {n_d} distinct")
    if n_s != n_p:
        problems.append(f"silver row count {n_s} differs from production {n_p}")
    mism = int(q.one(f"""SELECT count(*) FROM (SELECT code, last_modified_t, {h} hh FROM {T}) s
        FULL OUTER JOIN (SELECT code, last_modified_t, {h} hh FROM {P} WHERE source_file IN ({inlist(files)})) p
        ON s.code <=> p.code AND s.last_modified_t <=> p.last_modified_t
        WHERE s.hh IS NULL OR p.hh IS NULL OR s.hh <> p.hh"""))
    if mism:
        problems.append(f"{mism} silver rows missing, extra or different against production (the 2 known old-format delta rows differ: none -> legacy)")
    qs = int(q.one(f"""SELECT count(*) FROM (SELECT source_file, record_sha256 FROM {SCR_SILVER}.silver_quarantine) s
        FULL OUTER JOIN (SELECT source_file, record_sha256 FROM {PROD_SILVER}.silver_quarantine WHERE source_file IN ({inlist(files)})) p
        ON s.source_file = p.source_file AND s.record_sha256 = p.record_sha256 WHERE s.record_sha256 IS NULL OR p.record_sha256 IS NULL"""))
    if qs:
        problems.append(f"{qs} quarantine rows differ from production")
    man = q.run(f"SELECT file_name, rows_in, rows_silver, rows_quarantine FROM {SCR_SILVER}.silver_manifest")
    if sorted(r[0] for r in man) != sorted(files):
        problems.append(f"manifest rows {sorted(r[0] for r in man)} are not exactly one per file")
    for r in man:
        if int(r[1]) != int(r[2]) + int(r[3]):
            problems.append(f"{r[0]}: {r[1]} in != {r[2]} silver + {r[3]} quarantine")
    prod_man = {r[0]: tuple(r[1:]) for r in q.run(
        f"SELECT file_name, rows_in, rows_silver, rows_quarantine FROM {PROD_SILVER}.silver_manifest WHERE file_name IN ({inlist(files)})")}
    for r in man:
        if prod_man.get(r[0]) != tuple(r[1:]):
            problems.append(f"{r[0]}: manifest counts {tuple(r[1:])} differ from production {prod_man.get(r[0])}")
    return problems


def cmd_silver(w, q: Sql, args):
    wait_idle(w)
    state = load_state()
    files = state["files"]
    modes = ["first_write", "midway", "later_file", "first_write", "midway", "later_file"]
    out = []
    for i in range(args.trials):
        mode = modes[i % len(modes)]
        q.run(f"DROP SCHEMA IF EXISTS {SCR_SILVER} CASCADE")
        params = {"bronze_schema": SCR_SBRONZE, "silver_schema": SCR_SILVER, "ping_healthchecks": "false",
                  "only_files": ",".join(files), "bronze_result": "n/a"}
        waiter = submit(w, f"packsense-kill-silver-{i + 1}", SILVER_NB, {**params, "run_id": f"kill-s-{i + 1}"}, args.branch)

        def snap():
            d, rec = silver_snapshot(q)
            return len(d), len(rec)
        killed, _, timing = trial_loop(w, q, waiter.run_id, mode, len(files), snap)
        rec = {"trial": i + 1, "mode": mode, "killed": killed}
        if timing:
            rec.update(timing)
        if killed:
            d, recd = silver_snapshot(q)
            rec.update(files_with_data=len(d), files_recorded=len(recd), window=silver_window(d, recd, len(files)))
            life, res, _ = run_state(w, waiter.run_id)
            rec["killed_run_state"] = res or life
        else:
            rec["note"] = "the run finished before the kill rule fired: not a kill trial"
        print(f"trial {i + 1}: {rec}", flush=True)
        rw = submit(w, f"packsense-kill-silver-{i + 1}-recover", SILVER_NB, {**params, "run_id": f"kill-s-{i + 1}-recover"}, args.branch)
        res, r = wait_terminal(w, rw.run_id)
        text, err = run_output(w, r)
        rec.update(recovery_state=res, recovery_output=text, recovery_error=err)
        rec["problems"] = verify_silver(q, files) if res == "SUCCESS" else [f"recovery run ended {res}: {err}"]
        print(f"   recovery: {res} {text} -> problems: {rec['problems'] or 'none'}", flush=True)
        out.append(rec)
    state["results"]["silver"] = out
    save_state(state)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["setup", "bronze", "silver", "cleanup"])
    ap.add_argument("--env-file", help="optional: otherwise DATABRICKS_HOST and DATABRICKS_TOKEN must already be in the environment")
    ap.add_argument("--branch", default="main", help="git branch the notebooks run from")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--files-n", type=int, default=6, help="setup only: how many delta files the trials use (a longer run gives the kill more time to land mid-write)")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    w = client()
    q = Sql(w)
    {"setup": cmd_setup, "bronze": cmd_bronze, "silver": cmd_silver, "cleanup": cmd_cleanup}[args.command](w, q, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
