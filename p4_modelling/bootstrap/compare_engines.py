"""Compares the portable gold models between Databricks and DuckDB (design 6.6, the P4 exit gate).

  dump  --engine databricks --env-file .env     summarise the models in the throwaway schema workspace.packsense_fixture
                                                 and write the golden file p4_modelling/fixtures/golden.json
                                                 (optionally --rows-out PATH: the full canonical rows, for diagnosing a difference)
  check [--duckdb target/fixture.duckdb]         summarise the DuckDB models and compare with the golden file; exit 1 on any difference
                                                 (optionally --rows-ref PATH: name the differing columns using the rows file)
Run from the repo root with the dbt environment (it holds duckdb and the Databricks SDK): .venv-dbt\\Scripts\\python.exe
The Databricks side needs DATABRICKS_HOST and DATABRICKS_TOKEN (admin; or --env-file) and a warehouse (DBT_HTTP_PATH or --warehouse-path).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gold_lib import compare  # noqa: E402

GOLDEN = ROOT / "fixtures" / "golden.json"
FIXTURE_SCHEMA = "workspace.packsense_fixture"
DEFAULT_WAREHOUSE = "/sql/1.0/warehouses/c9e35ecf0a03295d"   # the Serverless Starter 2X-Small: an address, not a secret


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def duckdb_models(path: str):
    import duckdb
    con = duckdb.connect(path, read_only=True)
    out, rows_out = {}, {}
    for model in compare.MODELS:
        cur = con.execute(f'select * from "main"."{model}"')
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        out[model] = compare.summarise(model, cols, rows)
        rows_out[model] = {compare.key_of(r, compare.MODELS[model]): {k: compare.norm(v) for k, v in r.items()} for r in rows}
    con.close()
    return out, rows_out


def databricks_models():
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    warehouse = os.environ.get("DBT_HTTP_PATH", DEFAULT_WAREHOUSE).rstrip("/").split("/")[-1]
    out, rows_out = {}, {}
    for model in compare.MODELS:
        r = w.statement_execution.execute_statement(warehouse_id=warehouse, statement=f"select * from {FIXTURE_SCHEMA}.{model}", wait_timeout="50s")
        while r.status.state.value in ("PENDING", "RUNNING"):
            time.sleep(2)
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"{model}: {r.status.state.value} {r.status.error}")
        cols = [(c.name, c.type_name.value if hasattr(c.type_name, "value") else str(c.type_name), c.type_text) for c in r.manifest.schema.columns]
        rows, chunk = [], r.result
        while chunk is not None:
            for cells in chunk.data_array or []:
                rows.append({name: compare.from_databricks(cell, tname, ttext) for (name, tname, ttext), cell in zip(cols, cells)})
            nxt = getattr(chunk, "next_chunk_index", None)
            chunk = w.statement_execution.get_statement_result_chunk_n(r.statement_id, nxt) if nxt is not None else None
        out[model] = compare.summarise(model, [c for c, _, _ in cols], rows)
        rows_out[model] = {compare.key_of(x, compare.MODELS[model]): {k: compare.norm(v) for k, v in x.items()} for x in rows}
        print(f"{model}: {len(rows)} rows")
    return out, rows_out


def run_dbt_build(duckdb_path: str, extra=()) -> None:
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    env = dict(os.environ, DUCKDB_PATH=str(Path(duckdb_path).resolve()))
    r = subprocess.run([str(exe), "build", "--target", "duckdb", "--profiles-dir", str(ROOT), *extra], cwd=str(ROOT), env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        raise RuntimeError(f"dbt build {' '.join(extra)} failed")


def idempotence(duckdb_path: str) -> list:
    """Three rebuilds must reproduce the first build exactly. Returns the list of problems (empty = idempotent)."""
    from gold_lib import fixture_load
    import duckdb
    problems = []
    base, _ = duckdb_models(duckdb_path)

    run_dbt_build(duckdb_path)
    again, _ = duckdb_models(duckdb_path)
    problems += [f"second build: {p}" for p in compare.diff(base, again)]
    print("second build vs first: " + ("identical" if not compare.diff(base, again) else "DIFFERENT"))

    run_dbt_build(duckdb_path, ["--full-refresh"])
    refreshed, _ = duckdb_models(duckdb_path)
    problems += [f"full refresh: {p}" for p in compare.diff(base, refreshed)]
    print("full refresh vs first: " + ("identical" if not compare.diff(base, refreshed) else "DIFFERENT"))

    # arrival order: the same rows stored in the opposite physical order (the seed arrived after newer deltas) must give the same gold
    rev = ROOT / "target" / "fixture_reversed.duckdb"
    for f in (rev, Path(str(rev) + ".wal")):
        f.unlink(missing_ok=True)
    con = duckdb.connect(str(rev))
    fixture_load.load(con, reverse=True)
    con.close()
    run_dbt_build(str(rev))
    reordered, _ = duckdb_models(str(rev))
    problems += [f"reverse order: {p}" for p in compare.diff(base, reordered)]
    print("reverse-order load vs first: " + ("identical" if not compare.diff(base, reordered) else "DIFFERENT"))
    return problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")   # names in many scripts: a Windows console must not crash the report
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("idempotence")
    i.add_argument("--duckdb", default=str(ROOT / "target" / "fixture.duckdb"))
    d = sub.add_parser("dump")
    d.add_argument("--engine", choices=["databricks"], required=True)
    d.add_argument("--env-file")
    d.add_argument("--rows-out")
    c = sub.add_parser("check")
    c.add_argument("--duckdb", default=str(ROOT / "target" / "fixture.duckdb"))
    c.add_argument("--golden", default=str(GOLDEN))
    c.add_argument("--rows-ref")
    args = ap.parse_args()

    if args.cmd == "idempotence":
        problems = idempotence(args.duckdb)
        if problems:
            print("NOT IDEMPOTENT:")
            for p in problems:
                print(" -", p)
            return 1
        print("IDEMPOTENT: a second build, a full refresh and a reverse-order load all reproduce the first build exactly")
        return 0

    if args.cmd == "dump":
        if args.env_file:
            load_env_file(args.env_file)
        summary, rows = databricks_models()
        GOLDEN.write_text(json.dumps(summary, sort_keys=True, indent=0) + "\n", encoding="utf-8", newline="\n")
        print("golden written:", GOLDEN, GOLDEN.stat().st_size, "bytes")
        if args.rows_out:
            Path(args.rows_out).write_text(json.dumps(rows, sort_keys=True, ensure_ascii=False), encoding="utf-8")
            print("full rows written:", args.rows_out)
        return 0

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    summary, rows = duckdb_models(args.duckdb)
    problems = compare.diff(golden, summary)
    if problems and args.rows_ref:
        ref = json.loads(Path(args.rows_ref).read_text(encoding="utf-8"))
        for model, got in rows.items():
            shown = 0
            for k, row in got.items():
                if k in ref.get(model, {}) and compare.column_diff(ref[model][k], row) and shown < 3:
                    problems.append(f"{model} {k}: differing columns {compare.column_diff(ref[model][k], row)}")
                    shown += 1
    for model, s in summary.items():
        print(f"{model}: {s['rows']} rows")
    if problems:
        print("ENGINES DIFFER:")
        for p in problems:
            print(" -", p)
        return 1
    print("IDENTICAL: every portable model has the same rows on Databricks (golden) and DuckDB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
