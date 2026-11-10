"""Run ONE read-only SELECT (given in a file) on the SQL warehouse, print the rows (counts only, by the caller's choice), stop the warehouse.

  python p8_steward/readonly_sql.py --env-file .env --sql-file path.sql

Refuses anything that does not start with select or with. Used for one-off counts; prints nothing but the result rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from history_key_fetch import load_env_file  # noqa: E402


def is_read_only(sql: str) -> bool:
    return sql.strip().lower().startswith(("select", "with")) and ";" not in sql.strip().rstrip(";")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--sql-file", required=True)
    ap.add_argument("--out", help="write the rows as JSON lines (column names from the result) instead of printing them")
    a = ap.parse_args()
    sql = Path(a.sql_file).read_text(encoding="utf8")
    if not is_read_only(sql):
        sys.exit("refused: only a single select or with statement")
    load_env_file(a.env_file)
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(name, None)
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    wh = next(iter(w.warehouses.list())).id
    try:
        r = w.statement_execution.execute_statement(warehouse_id=wh, statement=sql, wait_timeout="50s")
        if r.status.state.value != "SUCCEEDED":
            sys.exit(f"query state: {r.status.state.value} {r.status.error.message if r.status.error else ''}")
        rows = list(r.result.data_array or [])
        nxt = r.result.next_chunk_index
        while nxt is not None:
            ch = w.statement_execution.get_statement_result_chunk_n(r.statement_id, nxt)
            rows += ch.data_array or []
            nxt = ch.next_chunk_index
        if a.out:
            names = [c.name for c in r.manifest.schema.columns]
            with open(a.out, "w", encoding="utf8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(dict(zip(names, row)), ensure_ascii=False, sort_keys=True) + "\n")
            print("rows written:", len(rows), "->", a.out)
        else:
            for row in rows:
                print(*row, sep=" | ")
    finally:
        w.warehouses.stop(wh)
        print("SQL warehouse stop requested")
    return 0


if __name__ == "__main__":
    sys.exit(main())
