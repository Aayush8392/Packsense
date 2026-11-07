"""Rebuild drill, P9: landing is lost and only the Hugging Face archive is left. Rebuild bronze and silver for the days that exist ONLY in the
archive (loaded by production, but no longer in landing, which keeps 30 days) and compare them with production.

What it does (scratch areas only; production tables are only read and their counts are compared before and after):
  1. finds the delta files production has loaded in bronze AND silver that are no longer in landing/deltas;
  2. fetches them (and all capture manifests) from the private archive repo into landing/_test_rebuild, inside Databricks; no B2 call;
     checks each file's sha256 three ways: the restored copy, the archive manifest, and the hash the capture recorded in production bronze;
  3. runs the real bronze notebook ONCE, then the real silver notebook ONCE, on workspace.ps_rebuild_bronze / ps_rebuild_silver;
  4. compares both with production for those files (the checks of crash_test.py) and runs both notebooks a SECOND time: nothing may change;
  5. drops the scratch schemas, removes the copy, compares the production fingerprint, stops the SQL warehouse, prints seconds and run ids.

  python p2_lakehouse/bootstrap/rebuild_drill.py plan  --env-file PATH     read only: how many files, MB, rows
  python p2_lakehouse/bootstrap/rebuild_drill.py run   --env-file PATH [--branch main]
  python p2_lakehouse/bootstrap/rebuild_drill.py usage --env-file PATH     DBU of the runs of the last `run` (billing lags by hours)
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed. The fetch reads the archive token from the secret scope as the admin.
The seed load (the first bronze rows, from the dump repo) is not part of this drill: the archive holds the delta files since the capture began.
"""
import argparse
import base64
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crash_test as ct  # noqa: E402
import outage_drill as od  # noqa: E402  (end_time, gaps, span_days, second_pass_problems, verdict, run_step)

HF_REPO = "Anonymous8392/packsense-archive"
REBUILD_LANDING = ct.LANDING + "/_test_rebuild"
SCR_BRONZE = "workspace.ps_rebuild_bronze"
SCR_SILVER = "workspace.ps_rebuild_silver"
# verify_bronze / verify_silver read these module names (set after the import of outage_drill, which sets its own)
ct.TEST_LANDING, ct.SCR_BRONZE, ct.SCR_SILVER = REBUILD_LANDING, SCR_BRONZE, SCR_SILVER
STATE_FILE = Path(tempfile.gettempdir()) / "packsense_rebuild_drill.json"

HELPER = '''# Databricks notebook source
# MAGIC %pip install -q huggingface_hub

# COMMAND ----------
import hashlib, json, os, shutil
from huggingface_hub import HfApi, hf_hub_download
dbutils.widgets.text("mode", "restore")
dbutils.widgets.text("names", "")
dbutils.widgets.text("dst", "")
dbutils.widgets.text("repo", "")
mode, dst, repo = dbutils.widgets.get("mode"), dbutils.widgets.get("dst"), dbutils.widgets.get("repo")
names = [n for n in dbutils.widgets.get("names").split(",") if n]
assert dst.endswith("/_test_rebuild"), "refusing to touch anything but the scratch folder"

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

if mode == "restore":
    token = dbutils.secrets.get("packsense", "hf_archive_token")
    api = HfApi(token=token)
    files = set(api.list_repo_files(repo, repo_type="dataset"))
    manifests = sorted(f for f in files if f.startswith("raw/manifests/") and f.endswith(".json"))
    archive = json.load(open(hf_hub_download(repo, "archive/manifest.json", repo_type="dataset", token=token, local_dir="/tmp/hf_rebuild", force_download=True)))
    os.makedirs(dst + "/deltas", exist_ok=True)
    os.makedirs(dst + "/manifests", exist_ok=True)
    restored, archive_sha, missing = {}, {}, []
    for n in names:
        key = f"raw/deltas/{n}"
        if key not in files:
            missing.append(n)
            continue
        local = hf_hub_download(repo, key, repo_type="dataset", token=token, local_dir="/tmp/hf_rebuild")
        shutil.copyfile(local, f"{dst}/deltas/{n}")
        restored[n] = sha(f"{dst}/deltas/{n}")
        archive_sha[n] = (archive.get("files", {}).get(key) or {}).get("sha256")
        os.remove(local)
    for m in manifests:
        p = hf_hub_download(repo, m, repo_type="dataset", token=token, local_dir="/tmp/hf_rebuild")
        shutil.copyfile(p, f"{dst}/manifests/{os.path.basename(m)}")
    dbutils.notebook.exit(json.dumps({"restored": restored, "archive_sha": archive_sha, "missing": missing, "manifests": len(manifests)}))
elif mode == "remove":
    dbutils.fs.rm(dst, True)
    dbutils.notebook.exit("removed")
'''


# ---- pure logic (unit-tested) ------------------------------------------------------------------------------------------

end_time = od.end_time


def archive_only(done_bronze: set, done_silver: set, landing: set) -> list:
    """Delta files production finished in both layers that landing no longer holds, oldest first."""
    return sorted((f for f in done_bronze & done_silver if end_time(f) is not None and f not in landing), key=end_time)


def require_files(files: list) -> list:
    if not files:
        raise ValueError("nothing to rebuild: every loaded day is still in landing")
    return files


def sha_problems(files: list, restored: dict, archive_sha: dict, capture_sha: dict) -> list:
    """The restored copy, the archive manifest and the capture's recorded hash must all be equal, for every file."""
    problems = []
    for f in files:
        if f not in restored:
            problems.append(f"{f}: not restored from the archive")
            continue
        if not archive_sha.get(f):
            problems.append(f"{f}: no sha256 in the archive manifest")
        elif archive_sha[f] != restored[f]:
            problems.append(f"{f}: restored copy differs from the archive manifest")
        if not capture_sha.get(f):
            problems.append(f"{f}: no sha256 recorded by the capture in production bronze")
        elif capture_sha[f] != restored[f]:
            problems.append(f"{f}: restored copy differs from the hash the capture recorded")
    return problems


# ---- Databricks side ---------------------------------------------------------------------------------------------------

def find_set(w, q):
    f = od.fleet(w, q)
    return require_files(archive_only(f["done_b"], f["done_s"], set(f["sizes"])))


def counts(q) -> dict:
    t = {"bronze_rows": f"{SCR_BRONZE}.bronze_delta_raw", "bronze_manifest": f"{SCR_BRONZE}.bronze_manifest",
         "silver_rows": f"{SCR_SILVER}.silver_product_versions", "silver_quarantine": f"{SCR_SILVER}.silver_quarantine",
         "silver_manifest": f"{SCR_SILVER}.silver_manifest"}
    return {k: int(q.one(f"SELECT count(*) FROM {v}")) for k, v in t.items()}


def cmd_plan(w, q, args):
    files = find_set(w, q)
    rows = od.prod_rows(q, files)
    print(f"{len(files)} delta files are in production bronze and silver but no longer in landing (archive only)")
    print(f"  oldest {files[0]}, newest {files[-1]}, span {od.span_days(files):.1f} days, gaps: {len(od.gaps(files))}, {rows} bronze rows in production")


def cmd_run(w, q, args):
    before = ct.fingerprint(q)
    files = find_set(w, q)
    rows = od.prod_rows(q, files)
    capture_sha = {r[0]: r[1] for r in q.run(f"SELECT file_name, file_sha256 FROM {ct.PROD_BRONZE}.bronze_manifest WHERE file_name IN ({ct.inlist(files)})")}
    print(f"{len(files)} archive-only days, span {od.span_days(files):.1f} days, gaps: {od.gaps(files) or 'none'}, {rows} production bronze rows", flush=True)
    started = datetime.now(timezone.utc)
    log, sha_p, b_problems, s_problems, second = [], [], [], [], []
    nb = ct.helper_notebook_path(w).replace("crash_test_copy", "rebuild_drill_helper")
    try:
        from databricks.sdk.service.workspace import ImportFormat, Language
        w.workspace.import_(path=nb, content=base64.b64encode(HELPER.encode()).decode(), format=ImportFormat.SOURCE,
                            language=Language.PYTHON, overwrite=True)
        ct.wait_idle(w)
        res, text, err = od.run_step(w, "fetch", nb, {"mode": "restore", "names": ",".join(files), "dst": REBUILD_LANDING, "repo": HF_REPO}, args.branch, log, True)
        if res != "SUCCESS":
            sha_p.append(f"fetch from the archive failed: {err}")
            return 1
        info = json.loads(text)
        sha_p += [f"{m}: not in the archive" for m in info["missing"]]
        sha_p += sha_problems(files, info["restored"], info["archive_sha"], capture_sha)
        print(f"fetched {len(info['restored'])} of {len(files)} files and {info['manifests']} manifests; sha256 problems: {len(sha_p)}", flush=True)
        if sha_p:
            return 1

        q.run(f"DROP SCHEMA IF EXISTS {SCR_BRONZE} CASCADE")
        q.run(f"DROP SCHEMA IF EXISTS {SCR_SILVER} CASCADE")
        q.run(f"CREATE SCHEMA {SCR_BRONZE}")
        bp = {"landing": REBUILD_LANDING, "bronze_schema": SCR_BRONZE}
        sp = {"bronze_schema": SCR_BRONZE, "silver_schema": SCR_SILVER, "ping_healthchecks": "false", "only_files": ",".join(files), "bronze_result": "n/a"}
        res, _, err = od.run_step(w, "rebuild-bronze-1", ct.BRONZE_NB, {**bp, "run_id": "rebuild-b1"}, args.branch, log)
        if res != "SUCCESS":
            b_problems.append(f"bronze run ended {res}: {err}")
            return 1
        b_problems += ct.verify_bronze(q, files)
        res, _, err = od.run_step(w, "rebuild-silver-1", ct.SILVER_NB, {**sp, "run_id": "rebuild-s1"}, args.branch, log)
        if res != "SUCCESS":
            s_problems.append(f"silver run ended {res}: {err}")
            return 1
        s_problems += ct.verify_silver(q, files)
        after_first = counts(q)
        print("after one pass over the rebuilt days:", after_first, flush=True)

        res, _, err = od.run_step(w, "rebuild-bronze-2", ct.BRONZE_NB, {**bp, "run_id": "rebuild-b2"}, args.branch, log)
        res2, _, err2 = od.run_step(w, "rebuild-silver-2", ct.SILVER_NB, {**sp, "run_id": "rebuild-s2"}, args.branch, log)
        if res != "SUCCESS" or res2 != "SUCCESS":
            second.append(f"second pass ended {res} / {res2}: {err} {err2}")
        else:
            second += od.second_pass_problems(after_first, counts(q))
            b_problems += [f"(after second pass) {p}" for p in ct.verify_bronze(q, files)]
            s_problems += [f"(after second pass) {p}" for p in ct.verify_silver(q, files)]
        return 0
    finally:
        for s in (SCR_BRONZE, SCR_SILVER):
            q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
        if log:
            od.run_step(w, "rebuild-remove", nb, {"mode": "remove", "dst": REBUILD_LANDING}, args.branch, log, True)
        try:
            w.workspace.delete(nb)
        except Exception as e:
            print("helper notebook not deleted:", type(e).__name__)
        after = ct.fingerprint(q)
        left = int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_rebuild%'") or 0)
        print("production before:", before)
        print("production after: ", after, "(UNCHANGED)" if after == before else "(DIFFERS: check whether a scheduled run happened meanwhile)")
        print("scratch schemas left:", left)
        try:
            for wh in w.warehouses.list():
                w.warehouses.stop(wh.id)
            print("SQL warehouse stop requested")
        except Exception as e:
            print("warehouse not stopped:", type(e).__name__, "(stop it by hand)")
        v = od.verdict(sha_p + b_problems, s_problems, second)
        notebook_seconds = sum(x["seconds"] for x in log)
        print(f"VERDICT: {v}")
        for p in sha_p + b_problems + s_problems + second:
            print("  problem:", p)
        print(f"COST: {len(files)} days, {rows} rows, {len(log)} notebook runs, {notebook_seconds:.0f} s of notebook time in all;"
              f" wall clock {(datetime.now(timezone.utc) - started).total_seconds():.0f} s (the SQL warehouse was awake for that long)")
        STATE_FILE.write_text(json.dumps({"days": len(files), "rows": rows, "started": started.isoformat(), "runs": log,
                                          "notebook_seconds": notebook_seconds, "verdict": v}, indent=1), encoding="utf-8")


def cmd_usage(w, q, args):
    if not STATE_FILE.exists():
        sys.exit(f"no state file {STATE_FILE}: run the drill first")
    st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    ids = ",".join(str(r["run_id"]) for r in st["runs"])
    rows = q.run(f"SELECT sku_name, round(sum(usage_quantity), 3) FROM system.billing.usage WHERE usage_metadata.job_run_id IN ({ids}) GROUP BY sku_name")
    print("DBU of the drill's notebook runs:", rows or "no rows yet (billing lags by hours)")
    print(f"drill: {st['days']} days, {st['rows']} rows, {st['notebook_seconds']:.0f} s notebook time, verdict {st['verdict']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["plan", "run", "usage"])
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--branch", default="main", help="git branch the notebooks run from")
    args = ap.parse_args()
    ct.load_env_file(args.env_file)
    w = ct.client()
    q = ct.Sql(w)
    return {"plan": cmd_plan, "run": cmd_run, "usage": cmd_usage}[args.command](w, q, args) or 0


if __name__ == "__main__":
    sys.exit(main())
