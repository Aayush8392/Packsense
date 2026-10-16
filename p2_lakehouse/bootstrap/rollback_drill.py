"""Drill of docs/runbook-rollback.md (sections A and B: revert code, repair data) on scratch schemas only. Run it from the repo root.

Procedure:
  1. a throwaway branch `rollback-drill-bad` holds one deliberate silent bug (13-digit codes labelled gtin12: no error, wrong data);
     `rollback-drill-fixed` is that branch plus a real `git revert` of the bug; both are pushed, neither is ever merged;
  2. python p2_lakehouse/bootstrap/rollback_drill.py run --env-file .env
  3. python p2_lakehouse/bootstrap/rollback_drill.py cleanup --env-file .env
  4. delete both drill branches (local and remote).

`run`: scratch copy of the 4 newest real delta files, A = 2 files, B = 2 files. Silver with the good code (git main) on A; note the
version of each silver table (runbook step B2); silver with the bad code on B -> the bad data lands and is measured against production;
RESTORE the three silver tables to the noted versions (B3) and check the state equals "A only"; silver with the reverted code on B
(rollback-drill-fixed); compare A+B with production (B5). Also checks how far back Delta time travel reaches. Production is only read.
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

BR, SI = "workspace.ps_rollback_bronze", "workspace.ps_rollback_silver"
PB, PS = ct.PROD_BRONZE, ct.PROD_SILVER
RUN_COLS = {"bronze_ingested_at", "silver_processed_at", "job_run_id", "silver_contract_version"}
TABLES = ("silver_product_versions", "silver_quarantine", "silver_manifest")


def run_silver(w, name, branch, params, files):
    t0 = time.time()
    waiter = ct.submit(w, name, ct.SILVER_NB, {**params, "only_files": ",".join(files), "run_id": name}, branch)
    res, r = ct.wait_terminal(w, waiter.run_id, 30)
    text, err = ct.run_output(w, r)
    secs = round(time.time() - t0)
    print(f"{name} (branch {branch}): {res} in {secs} s {text[:200]} {err}", flush=True)
    if res != "SUCCESS":
        sys.exit(f"{name} failed")
    return secs


def versions(q):
    """The latest Delta version of each silver table (DESCRIBE HISTORY lists the newest first)."""
    return {t: int(q.run(f"DESCRIBE HISTORY {SI}.{t} LIMIT 1")[0][0]) for t in TABLES}


def cmd_run(w, q, args):
    c = contract.load()
    cols = [x["name"] for x in c["columns"] if x["name"] not in RUN_COLS]
    newest = [r[0] for r in q.run(
        f"SELECT file_name FROM {PS}.silver_manifest WHERE file_name LIKE 'openfoodfacts_products_%' ORDER BY file_name DESC LIMIT 4")]
    a_files, b_files = sorted(newest[2:]), sorted(newest[:2])
    all_files = a_files + b_files
    inl = ct.inlist(all_files)
    print("A (good code first):", len(a_files), "files | B (bad run, then repaired):", len(b_files), "files")

    for s in (BR, SI):
        q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    q.run(f"CREATE SCHEMA {BR}")
    q.run(f"CREATE TABLE {BR}.bronze_delta_raw AS SELECT * FROM {PB}.bronze_delta_raw WHERE source_file IN ({inl})")
    q.run(f"CREATE TABLE {BR}.bronze_manifest AS SELECT * FROM {PB}.bronze_manifest WHERE file_name IN ({inl})")
    print("scratch bronze rows:", q.one(f"SELECT count(*) FROM {BR}.bronze_delta_raw"))
    params = {"bronze_schema": BR, "silver_schema": SI, "ping_healthchecks": "false", "bronze_result": "n/a"}
    T = f"{SI}.silver_product_versions"
    timings = {}

    timings["good run on A"] = run_silver(w, "rollback-good-A", "main", params, a_files)
    n_a = int(q.one(f"SELECT count(*) FROM {T}"))
    good_versions = versions(q)
    print(f"A only: {n_a} silver rows; last good versions {good_versions}")

    timings["bad run on B"] = run_silver(w, "rollback-bad-B", "rollback-drill-bad", params, b_files)
    n_ab = int(q.one(f"SELECT count(*) FROM {T}"))
    wrong = int(q.one(f"SELECT count(*) FROM {T} t JOIN {PS}.silver_product_versions p ON t.code <=> p.code AND t.last_modified_t <=> p.last_modified_t "
                      f"WHERE t.code_kind <> p.code_kind"))
    print(f"after the bad run: {n_ab} rows, of which {wrong} have a code_kind different from production (the bad data, with no error raised)")
    if not wrong:
        sys.exit("the bad run produced no visible wrong data: the drill cannot show a repair")

    t0 = time.time()
    for t, v in good_versions.items():                                    # runbook B3
        q.run(f"RESTORE TABLE {SI}.{t} TO VERSION AS OF {v}")
    timings["RESTORE of 3 tables"] = round(time.time() - t0)
    n_back = int(q.one(f"SELECT count(*) FROM {T}"))
    m_back = int(q.one(f"SELECT count(*) FROM {SI}.silver_manifest"))
    wrong_back = int(q.one(f"SELECT count(*) FROM {T} t JOIN {PS}.silver_product_versions p ON t.code <=> p.code AND t.last_modified_t <=> p.last_modified_t "
                           f"WHERE t.code_kind <> p.code_kind"))
    print(f"after RESTORE: {n_back} rows (expected {n_a}), {m_back} manifest rows (expected {len(a_files)}), {wrong_back} wrong rows")

    timings["repair run on B"] = run_silver(w, "rollback-repair-B", "rollback-drill-fixed", params, b_files)

    problems = []
    if n_back != n_a or m_back != len(a_files) or wrong_back:
        problems.append("RESTORE did not return the tables to the state after the good run")
    h = "md5(to_json(struct(" + ", ".join(f"`{n}`" for n in cols) + ")))"
    n_fin = int(q.one(f"SELECT count(*) FROM {T}"))
    n_prod = int(q.one(f"SELECT count(*) FROM {PS}.silver_product_versions WHERE source_file IN ({inl})"))
    dup = int(q.one(f"SELECT count(*) FROM (SELECT code, last_modified_t FROM {T} GROUP BY 1, 2 HAVING count(*) > 1)"))
    diff = int(q.one(f"SELECT count(*) FROM (SELECT code, last_modified_t, {h} hh FROM {T}) s FULL OUTER JOIN "
                     f"(SELECT code, last_modified_t, {h} hh FROM {PS}.silver_product_versions WHERE source_file IN ({inl})) p "
                     f"ON s.code <=> p.code AND s.last_modified_t <=> p.last_modified_t WHERE s.hh IS NULL OR p.hh IS NULL OR s.hh <> p.hh"))
    man = q.run(f"SELECT file_name, rows_in, rows_silver, rows_quarantine FROM {SI}.silver_manifest")
    if n_fin != n_prod:
        problems.append(f"row count {n_fin} differs from production {n_prod}")
    if dup:
        problems.append(f"{dup} duplicate keys")
    if diff:
        problems.append(f"{diff} rows differ from production after the repair")
    if sorted(r[0] for r in man) != sorted(all_files) or any(int(r[1]) != int(r[2]) + int(r[3]) for r in man):
        problems.append("manifest is not one balanced row per file")
    print(f"after the repair: {n_fin} rows (production {n_prod}), {dup} duplicate keys, {diff} rows differ from production")

    first = int(q.one(f"SELECT count(*) FROM {T} VERSION AS OF 0"))
    hist = q.run(f"DESCRIBE HISTORY {T}")
    print(f"time travel: the table has {len(hist)} versions listed, version 0 is readable ({first} rows); "
          f"restored versions {good_versions}")
    print("timings (seconds, each silver run includes about a minute of job start-up):", timings)
    print("problems:", problems or "none")
    print("RESULT:", "PASS" if not problems else "FAIL")


def cmd_cleanup(w, q, args):
    for s in (BR, SI):
        q.run(f"DROP SCHEMA IF EXISTS {s} CASCADE")
    left = int(q.one("SELECT count(*) FROM system.information_schema.schemata WHERE schema_name LIKE 'ps_rollback%'") or 0)
    print("scratch schemas left:", left)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "cleanup"])
    ap.add_argument("--env-file")
    a = ap.parse_args()
    if a.env_file:
        ct.load_env_file(a.env_file)
    w = ct.client()
    q = ct.Sql(w)
    {"run": cmd_run, "cleanup": cmd_cleanup}[a.command](w, q, a)


if __name__ == "__main__":
    main()
