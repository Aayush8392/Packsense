"""The Databricks half of the engine comparison: a THROWAWAY schema, admin only, dropped afterwards.

  load  --env-file .env     create workspace.packsense_fixture, upload the fixture to the dev landing volume and load it as
                            the table fixture_stg_silver_versions with the manifest's exact column types
  dbt   --env-file .env     run `dbt build` on it (target fixture_admin, var fixture_mode): the portable models and their 42 tests
  drop  --env-file .env     drop the schema (CASCADE) and remove the uploaded file (cleanup)
Run from the repo root with the dbt environment: .venv-dbt\\Scripts\\python.exe p4_modelling/bootstrap/fixture_databricks.py <cmd> --env-file .env
Nothing here touches dev or production gold, silver or bronze. Values from the env file are never printed.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

P4 = Path(__file__).resolve().parents[1]
FIXTURES = P4 / "fixtures"
SCHEMA = "workspace.packsense_fixture"
TABLE = f"{SCHEMA}.fixture_stg_silver_versions"
TAXONOMY_TABLE = f"{SCHEMA}.fixture_taxonomy_tag"
REMOTE_DIR = "/Volumes/workspace/packsense_dev/landing/_fixture_check"
REMOTE_FILE = f"{REMOTE_DIR}/stg_silver_versions.jsonl"
DEFAULT_HTTP_PATH = "/sql/1.0/warehouses/c9e35ecf0a03295d"   # the Serverless Starter 2X-Small: an address, not a secret


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def client():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")


def run_sql(w, statement: str):
    warehouse = os.environ.get("DBT_HTTP_PATH", DEFAULT_HTTP_PATH).rstrip("/").split("/")[-1]
    r = w.statement_execution.execute_statement(warehouse_id=warehouse, statement=statement, wait_timeout="50s")
    while r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"{r.status.state.value}: {r.status.error}")
    return r


def load_one(w, jsonl_name, manifest_name, table, volume_file) -> None:
    manifest = json.loads((FIXTURES / manifest_name).read_text(encoding="utf-8"))
    columns = manifest["columns"]
    # timestamps are read as text and cast, so the parsing does not depend on a reader option
    read_schema = ", ".join(f"`{n}` {'string' if t == 'timestamp' else t}" for n, t in columns.items())
    select = ", ".join(f"cast(`{n}` as timestamp) as `{n}`" if t == "timestamp" else f"`{n}`" for n, t in columns.items())
    body = (FIXTURES / jsonl_name).read_bytes()
    w.files.upload(volume_file, io.BytesIO(body), overwrite=True)
    print(f"uploaded {jsonl_name}: {len(body)} bytes")
    run_sql(w, f"create or replace table {table} as select {select} from read_files('{volume_file}', format => 'json', schema => '{read_schema}')")
    n = int(run_sql(w, f"select count(*) from {table}").result.data_array[0][0])
    if n != manifest["version_rows"]:
        sys.exit(f"{table}: loaded {n} rows, the manifest says {manifest['version_rows']}")
    print(f"loaded {n} rows into {table}")


def load() -> None:
    w = client()
    w.files.create_directory(REMOTE_DIR)
    run_sql(w, f"create schema if not exists {SCHEMA}")
    load_one(w, "stg_silver_versions.jsonl", "manifest.json", TABLE, REMOTE_FILE)
    if (FIXTURES / "taxonomy_manifest.json").exists():
        load_one(w, "taxonomy_tag.jsonl", "taxonomy_manifest.json", TAXONOMY_TABLE, f"{REMOTE_DIR}/taxonomy_tag.jsonl")


def dbt() -> int:
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    env = dict(os.environ)
    env.setdefault("DBT_HTTP_PATH", DEFAULT_HTTP_PATH)
    # this run signs in with the admin token only: a principal's client id and secret left in the shell make the driver see two methods
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        env.pop(name, None)
    cmd = [str(exe), "build", "--target", "fixture_admin", "--vars", "{fixture_mode: true}", "--profiles-dir", str(P4)]
    return subprocess.run(cmd, cwd=str(P4), env=env).returncode


def drop() -> None:
    w = client()
    run_sql(w, f"drop schema if exists {SCHEMA} cascade")
    try:
        for entry in list(w.files.list_directory_contents(REMOTE_DIR)):      # every file this script uploaded, then the folder
            w.files.delete(f"{REMOTE_DIR}/{entry.name}")
        w.files.delete_directory(REMOTE_DIR)
    except Exception as exc:   # already gone
        print("remote folder:", type(exc).__name__)
    print("dropped", SCHEMA, "and removed the uploaded file")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "dbt", "drop"])
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.cmd == "load":
        load()
    elif args.cmd == "drop":
        drop()
    else:
        return dbt()
    return 0


if __name__ == "__main__":
    sys.exit(main())
