"""One-day restore drill (A4 b): restore ONE real delta file and the capture manifests from the Hugging Face archive (not from B2, not from
landing), run the real bronze and silver notebooks on scratch schemas, and compare the result row for row with production.

What it proves: that the archive's copy of a day is complete and byte-identical (sha256 three ways: HF copy, landing copy, the hash the capture
recorded in production bronze) and that a rebuild from it reproduces production bronze and silver exactly (same checks as the kill test).

Everything happens in scratch areas; production tables are only read (counts are compared before and after):
  landing   /Volumes/workspace/packsense/landing/_test_restore   (the restored delta and every capture manifest, from HF)
  bronze    workspace.ps_restore_bronze        silver  workspace.ps_restore_silver
No B2 call (no daily-cap risk). HF has no published download cap; the file is one delta of 20 to 30 MB plus ten tiny manifests.

  python p2_lakehouse/bootstrap/restore_drill.py --env-file PATH [--file NAME] [--branch main]
The scratch areas are dropped at the end whatever happens. The silver run reads the real HMAC key from the secret scope as the admin (nothing printed).
"""
import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crash_test as ct  # noqa: E402  (reuses the Databricks plumbing and the bronze/silver comparison)

HF_REPO = "Anonymous8392/packsense-archive"
RESTORE_LANDING = ct.LANDING + "/_test_restore"
SCR_BRONZE = "workspace.ps_restore_bronze"
SCR_SILVER = "workspace.ps_restore_silver"
ct.TEST_LANDING, ct.SCR_BRONZE, ct.SCR_SILVER = RESTORE_LANDING, SCR_BRONZE, SCR_SILVER   # verify_bronze / verify_silver read these names

HELPER = '''# Databricks notebook source
# MAGIC %pip install -q huggingface_hub

# COMMAND ----------
import hashlib, json, os, shutil
from huggingface_hub import HfApi, hf_hub_download
dbutils.widgets.text("mode", "restore")
dbutils.widgets.text("name", "")
dbutils.widgets.text("dst", "")
dbutils.widgets.text("src", "")
dbutils.widgets.text("repo", "")
mode, name, dst, src, repo = (dbutils.widgets.get(k) for k in ("mode", "name", "dst", "src", "repo"))
assert dst.endswith("/_test_restore"), "refusing to touch anything but the scratch folder"

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

if mode == "restore":
    token = dbutils.secrets.get("packsense", "hf_archive_token")
    api = HfApi(token=token)
    files = api.list_repo_files(repo, repo_type="dataset")
    manifests = sorted(f for f in files if f.startswith("raw/manifests/") and f.endswith(".json"))
    assert f"raw/deltas/{name}" in files, "the delta is not in the archive: " + name
    os.makedirs(dst + "/deltas", exist_ok=True)
    os.makedirs(dst + "/manifests", exist_ok=True)
    local = hf_hub_download(repo, f"raw/deltas/{name}", repo_type="dataset", token=token, local_dir="/tmp/hf_restore")
    shutil.copyfile(local, f"{dst}/deltas/{name}")
    for m in manifests:
        p = hf_hub_download(repo, m, repo_type="dataset", token=token, local_dir="/tmp/hf_restore")
        shutil.copyfile(p, f"{dst}/manifests/{os.path.basename(m)}")
    out = {"hf_sha256": sha(f"{dst}/deltas/{name}"), "bytes": os.path.getsize(f"{dst}/deltas/{name}"), "manifests_restored": len(manifests)}
    if src and os.path.exists(f"{src}/deltas/{name}"):
        out["landing_sha256"] = sha(f"{src}/deltas/{name}")
    dbutils.notebook.exit(json.dumps(out))
elif mode == "remove":
    dbutils.fs.rm(dst, True)
    dbutils.notebook.exit("removed")
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--file", help="delta file name (default: the smallest delta in landing that production has fully loaded)")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    ct.load_env_file(args.env_file)
    w = ct.client()
    q = ct.Sql(w)
    before = ct.fingerprint(q)

    sizes = {i.name: i.file_size for i in w.files.list_directory_contents(f"{ct.LANDING}/deltas") if not i.is_directory}
    if args.file:
        name = args.file
    else:
        done_b = {r[0] for r in q.run(f"SELECT file_name FROM {ct.PROD_BRONZE}.bronze_manifest")}
        done_s = {r[0] for r in q.run(f"SELECT file_name FROM {ct.PROD_SILVER}.silver_manifest")}
        cands = {n: s for n, s in sizes.items() if n in done_b and n in done_s and n.startswith("openfoodfacts_products_")}
        name = min(cands, key=cands.get)
    prod_sha = q.one(f"SELECT file_sha256 FROM {ct.PROD_BRONZE}.bronze_manifest WHERE file_name = '{name}'")
    print("restoring", name, sizes.get(name), "bytes; the capture recorded sha256", prod_sha, flush=True)
    nb = ct.helper_notebook_path(w).replace("crash_test_copy", "restore_drill_helper")
    problems = []
    try:
        from databricks.sdk.service.workspace import ImportFormat, Language
        w.workspace.import_(path=nb, content=base64.b64encode(HELPER.encode()).decode(), format=ImportFormat.SOURCE,
                            language=Language.PYTHON, overwrite=True)
        ct.wait_idle(w)
        waiter = ct.submit(w, "packsense-restore-drill-fetch", nb, {"mode": "restore", "name": name, "dst": RESTORE_LANDING, "src": ct.LANDING,
                                                                    "repo": HF_REPO}, workspace=True)
        res, r = ct.wait_terminal(w, waiter.run_id)
        text, err = ct.run_output(w, r)
        print("restore from HF:", res, text, err, flush=True)
        if res != "SUCCESS":
            problems.append(f"restore failed: {err}")
            return 1
        info = json.loads(text)
        if info["hf_sha256"] != prod_sha:
            problems.append(f"HF copy sha256 {info['hf_sha256']} != the capture's recorded {prod_sha}")
        if info.get("landing_sha256") and info["landing_sha256"] != info["hf_sha256"]:
            problems.append("HF copy differs from the landing copy")
        print("sha256 three-way:", "HF", info["hf_sha256"][:16], "| landing", (info.get("landing_sha256") or "n/a")[:16], "| capture", prod_sha[:16], flush=True)

        q.run(f"DROP SCHEMA IF EXISTS {SCR_BRONZE} CASCADE")
        q.run(f"DROP SCHEMA IF EXISTS {SCR_SILVER} CASCADE")
        q.run(f"CREATE SCHEMA {SCR_BRONZE}")
        rb = ct.submit(w, "packsense-restore-drill-bronze", ct.BRONZE_NB, {"landing": RESTORE_LANDING, "bronze_schema": SCR_BRONZE, "run_id": "restore-b"}, args.branch)
        res, r = ct.wait_terminal(w, rb.run_id)
        text, err = ct.run_output(w, r)
        print("bronze on the restored file:", res, text, err, flush=True)
        if res != "SUCCESS":
            problems.append(f"bronze run ended {res}: {err}")
            return 1
        problems += ct.verify_bronze(q, [name])

        params = {"bronze_schema": SCR_BRONZE, "silver_schema": SCR_SILVER, "ping_healthchecks": "false", "only_files": name, "bronze_result": "n/a"}
        rs = ct.submit(w, "packsense-restore-drill-silver", ct.SILVER_NB, {**params, "run_id": "restore-s"}, args.branch)
        res, r = ct.wait_terminal(w, rs.run_id)
        text, err = ct.run_output(w, r)
        print("silver on the restored file:", res, text, err, flush=True)
        if res != "SUCCESS":
            problems.append(f"silver run ended {res}: {err}")
            return 1
        problems += ct.verify_silver(q, [name])
        n_b = q.one(f"SELECT count(*) FROM {SCR_BRONZE}.bronze_delta_raw")
        n_s = q.one(f"SELECT count(*) FROM {SCR_SILVER}.silver_product_versions")
        n_q = q.one(f"SELECT count(*) FROM {SCR_SILVER}.silver_quarantine")
        print(f"restored: bronze {n_b} rows, silver {n_s} rows, quarantine {n_q}", flush=True)
        return 0
    finally:
        for s in (SCR_BRONZE, SCR_SILVER):
            q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
        rm = ct.submit(w, "packsense-restore-drill-remove", nb, {"mode": "remove", "dst": RESTORE_LANDING}, workspace=True)
        res, _ = ct.wait_terminal(w, rm.run_id)
        print("remove restored copy:", res)
        try:
            w.workspace.delete(nb)
        except Exception as e:
            print("helper notebook not deleted:", type(e).__name__)
        after = ct.fingerprint(q)
        left = int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_restore%'") or 0)
        print("production before:", before)
        print("production after: ", after, "(UNCHANGED)" if after == before else "(DIFFERS: check whether a scheduled run happened meanwhile)")
        print("scratch schemas left:", left)
        print("PROBLEMS:", problems or "none")


if __name__ == "__main__":
    sys.exit(main())
