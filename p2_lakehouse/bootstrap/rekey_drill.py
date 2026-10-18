"""Drill of docs/runbook-rekey-hmac.md on scratch schemas only. Run it from the repo root.

Procedure (details and results in the runbook's "Drill" section):
  1. on a throwaway branch `rekey-drill`, make the runbook's step 2 and 3 edits (SECRET in create_hmac_key.py, hmac.secret_key and
     key_version in contracts/silver.yml, the version-1 pin in tests/test_transform.py), run the tests, and push the branch;
  2. with that branch checked out: python p2_lakehouse/bootstrap/create_hmac_key.py create --env-file .env   (makes hmac_key_v2)
  3. python p2_lakehouse/bootstrap/rekey_drill.py run --env-file .env
  4. python p2_lakehouse/bootstrap/rekey_drill.py cleanup --env-file .env
  5. python p2_lakehouse/bootstrap/rekey_drill.py delete-secret --env-file .env --yes     (the throwaway key, so a real re-key starts clean)
  6. return to main and delete the drill branch (it is never merged).

`run` does steps 4-6 of the runbook on a scratch copy of 6 real delta files (both quarantine files included): silver with hmac_key_v1
(git main) -> drop the three derived tables -> silver with hmac_key_v2 (git branch rekey-drill) -> verify. Production tables are only read. It also checks that distinct_editors (the one value gold derives from the codes) is identical under both keys.
Reads DATABRICKS_HOST and DATABRICKS_TOKEN from the file or the environment. Values are never printed.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "p2_lakehouse" / "bootstrap"))
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
import crash_test as ct  # noqa: E402
from silver_lib import contract  # noqa: E402

SCOPE, SECRET_V2 = "packsense", "hmac_key_v2"
BR, SI = "workspace.ps_rekey_bronze", "workspace.ps_rekey_silver"
PB, PS = ct.PROD_BRONZE, ct.PROD_SILVER
RUN_COLS = {"bronze_ingested_at", "silver_contract_version", "silver_processed_at", "job_run_id", "hmac_key_version"}


def timed_run(w, name, branch, params):
    t0 = time.time()
    waiter = ct.submit(w, name, ct.SILVER_NB, params, branch)
    res, r = ct.wait_terminal(w, waiter.run_id, 30)
    text, err = ct.run_output(w, r)
    secs = round(time.time() - t0)
    print(f"{name} (branch {branch}): {res} in {secs} s {text[:300]} {err}", flush=True)
    if res != "SUCCESS":
        sys.exit(f"{name} failed")
    return secs


def cmd_run(w, q, args):
    if not any(s.key == SECRET_V2 for s in w.secrets.list_secrets(scope=SCOPE)):
        sys.exit(f"{SECRET_V2} is not in scope {SCOPE}: create it first (create_hmac_key.py create, on the drill branch)")
    c = contract.load()
    cols = [x["name"] for x in c["columns"]]
    hashed = [x["name"] for x in c["columns"] if x["class"] == "hashed"]
    same_cols = [n for n in cols if n not in hashed and n not in RUN_COLS]
    print(f"{len(hashed)} hashed columns; {len(same_cols)} columns that must stay identical")

    qfiles = [r[0] for r in q.run(f"SELECT DISTINCT source_file FROM {PS}.silver_quarantine WHERE source_file LIKE 'openfoodfacts_products_%'")]
    others = [r[0] for r in q.run(
        f"SELECT file_name FROM {PS}.silver_manifest WHERE file_name LIKE 'openfoodfacts_products_%' AND file_name NOT IN ({ct.inlist(qfiles)}) ORDER BY rows_in")]
    k = 6 - len(qfiles)
    mid = (len(others) - k) // 2
    files = sorted(qfiles + others[mid:mid + k])
    print("files:", len(files), "| quarantine files among them:", len(qfiles))
    inl = ct.inlist(files)

    for s in (BR, SI):
        q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    q.run(f"CREATE SCHEMA {BR}")
    q.run(f"CREATE TABLE {BR}.bronze_delta_raw AS SELECT * FROM {PB}.bronze_delta_raw WHERE source_file IN ({inl})")
    q.run(f"CREATE TABLE {BR}.bronze_manifest AS SELECT * FROM {PB}.bronze_manifest WHERE file_name IN ({inl})")
    print("scratch bronze rows:", q.one(f"SELECT count(*) FROM {BR}.bronze_delta_raw"))

    params = {"bronze_schema": BR, "silver_schema": SI, "ping_healthchecks": "false", "only_files": ",".join(files), "bronze_result": "n/a"}
    t1 = timed_run(w, "packsense-rekey-drill-v1", "main", {**params, "run_id": "rekey-v1"})
    n1 = int(q.one(f"SELECT count(*) FROM {SI}.silver_product_versions"))
    nq1 = int(q.one(f"SELECT count(*) FROM {SI}.silver_quarantine"))
    q.run(f"CREATE TABLE {SI}.v1_silver AS SELECT * FROM {SI}.silver_product_versions")
    q.run(f"CREATE TABLE {SI}.v1_quarantine AS SELECT * FROM {SI}.silver_quarantine")
    print(f"v1: {n1} silver rows, {nq1} quarantine rows")

    for t in ("silver_product_versions", "silver_quarantine", "silver_manifest"):          # runbook step 5
        q.run(f"DROP TABLE {SI}.{t}")
    t2 = timed_run(w, "packsense-rekey-drill-v2", "rekey-drill", {**params, "run_id": "rekey-v2"})

    T, V = f"{SI}.silver_product_versions", f"{SI}.v1_silver"
    problems = []
    n2 = int(q.one(f"SELECT count(*) FROM {T}"))
    nq2 = int(q.one(f"SELECT count(*) FROM {SI}.silver_quarantine"))
    if (n2, nq2) != (n1, nq1):
        problems.append(f"counts differ: v1 {n1}+{nq1}, v2 {n2}+{nq2}")
    dup = int(q.one(f"SELECT count(*) FROM (SELECT code, last_modified_t FROM {T} GROUP BY 1, 2 HAVING count(*) > 1)"))
    if dup:
        problems.append(f"{dup} duplicate keys")
    bad_ver = int(q.one(f"SELECT count(*) FROM {T} WHERE hmac_key_version <> 2"))
    v1_ver = q.run(f"SELECT DISTINCT hmac_key_version FROM {V}")
    if bad_ver or [r[0] for r in v1_ver] != ["1"]:
        problems.append(f"key versions: {bad_ver} v2 rows not 2; v1 versions {v1_ver}")
    for h in hashed:
        stuck = int(q.one(f"SELECT count(*) FROM {T} t JOIN {V} v ON t.code <=> v.code AND t.last_modified_t <=> v.last_modified_t "
                          f"WHERE t.`{h}` IS NOT NULL AND cast(t.`{h}` AS STRING) NOT IN ('[]', '') AND t.`{h}` <=> v.`{h}`"))   # an empty list is the same under any key
        nullshift = int(q.one(f"SELECT count(*) FROM {T} t JOIN {V} v ON t.code <=> v.code AND t.last_modified_t <=> v.last_modified_t "
                              f"WHERE (t.`{h}` IS NULL) <> (v.`{h}` IS NULL)"))
        if stuck or nullshift:
            problems.append(f"{h}: {stuck} rows kept the old code, {nullshift} rows changed between null and not null")
    hh = "md5(to_json(struct(" + ", ".join(f"`{n}`" for n in same_cols) + ")))"
    diff = int(q.one(f"SELECT count(*) FROM (SELECT code, last_modified_t, {hh} h FROM {T}) a FULL OUTER JOIN "
                     f"(SELECT code, last_modified_t, {hh} h FROM {V}) b ON a.code <=> b.code AND a.last_modified_t <=> b.last_modified_t "
                     f"WHERE a.h IS NULL OR b.h IS NULL OR a.h <> b.h"))
    if diff:
        problems.append(f"{diff} rows differ in columns that must not change")
    # gold carries no code, only distinct_editors = size(array_distinct(editors_hmac)) (stg_silver_versions): it must be the same under any key
    de_sql = "SELECT code, last_modified_t, coalesce(size(array_distinct(editors_hmac)), 0) n FROM "
    de_diff = int(q.one(f"SELECT count(*) FROM ({de_sql}{T}) a FULL OUTER JOIN ({de_sql}{V}) b "
                        f"ON a.code <=> b.code AND a.last_modified_t <=> b.last_modified_t WHERE a.n IS NULL OR b.n IS NULL OR a.n <> b.n"))
    de_rows = int(q.one(f"SELECT count(*) FROM ({de_sql}{V}) WHERE n > 0"))
    if de_diff or de_rows == 0:
        problems.append(f"distinct_editors: {de_diff} rows differ between v1 and v2; {de_rows} rows have editors (0 would make the check empty)")
    print(f"distinct_editors identical under both keys on every row: {de_diff == 0} ({de_rows} of {n2} rows have at least one editor)")
    qd = int(q.one(f"SELECT count(*) FROM {SI}.silver_quarantine a JOIN {SI}.v1_quarantine b "
                   f"ON a.source_file = b.source_file AND a.record_sha256 = b.record_sha256 WHERE a.payload <> b.payload"))
    qm = int(q.one(f"SELECT count(*) FROM {SI}.silver_quarantine a FULL OUTER JOIN {SI}.v1_quarantine b "
                   f"ON a.source_file = b.source_file AND a.record_sha256 = b.record_sha256 WHERE a.record_sha256 IS NULL OR b.record_sha256 IS NULL"))
    if qm:
        problems.append(f"{qm} quarantine rows not matched between v1 and v2")
    man = q.run(f"SELECT file_name, rows_in, rows_silver, rows_quarantine FROM {SI}.silver_manifest")
    if sorted(r[0] for r in man) != files or any(int(r[1]) != int(r[2]) + int(r[3]) for r in man):
        problems.append("manifest is not one balanced row per file")
    print(f"quarantine payloads that changed with the key: {qd} of {nq2} (payloads carry hashed identities)")
    print(f"timings: silver v1 run {t1} s, rebuild with v2 {t2} s (each includes ~1 min of job start-up)")
    print("problems:", problems or "none")
    print("RESULT:", "PASS" if not problems else "FAIL")


def cmd_cleanup(w, q, args):
    for s in (BR, SI):
        q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    left = int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_rekey%'") or 0)
    print("scratch schemas left:", left)


def cmd_delete_secret(w, q, args):
    if not args.yes:
        sys.exit("add --yes to delete the throwaway hmac_key_v2 from the scope")
    w.secrets.delete_secret(scope=SCOPE, key=SECRET_V2)
    print("deleted", SECRET_V2, "| secrets in scope now:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "cleanup", "delete-secret"])
    ap.add_argument("--env-file")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    if a.env_file:
        ct.load_env_file(a.env_file)
    w = ct.client()
    q = ct.Sql(w)
    {"run": cmd_run, "cleanup": cmd_cleanup, "delete-secret": cmd_delete_secret}[a.command](w, q, a)


if __name__ == "__main__":
    main()
