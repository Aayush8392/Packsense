"""Read-only: fetch the CURRENT version history of the keyed products from production silver (the local review-set file is from 4 Nov).

  python p8_steward/history_key_fetch.py --env-file .env

One SELECT on workspace.packsense_silver.silver_product_versions for the codes in the four answer-key files; writes output/review_set/prod_versions_check.jsonl
(only the columns the check reads); stops the SQL warehouse afterwards. Prints counts, never a secret.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history_key_check as h  # noqa: E402

COLUMNS = ("code", "last_modified_t", "rev", "nutrition_per", "data_quality_errors_tags", *h.FIELDS)
OUT = h.REVIEW / "prod_versions_check.jsonl"


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    load_env_file(ap.parse_args().env_file)
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(name, None)
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    cards, _ = h.load()
    codes = ",".join(f"'{c}'" for c in cards)
    sql = f"select {', '.join(COLUMNS)} from workspace.packsense_silver.silver_product_versions where code in ({codes})"
    wh = next(iter(w.warehouses.list())).id
    try:
        r = w.statement_execution.execute_statement(warehouse_id=wh, statement=sql, wait_timeout="50s")
        if r.status.state.value != "SUCCEEDED":
            sys.exit(f"query state: {r.status.state.value} {r.status.error.message if r.status.error else ''}")
        rows = r.result.data_array or []
        # large results come in chunks
        nxt = r.result.next_chunk_index
        while nxt is not None:
            ch = w.statement_execution.get_statement_result_chunk_n(r.statement_id, nxt)
            rows += ch.data_array or []
            nxt = ch.next_chunk_index
        numeric = {"last_modified_t", "rev", *h.FIELDS}
        with OUT.open("w", encoding="utf8", newline="\n") as f:
            for row in rows:
                d = dict(zip(COLUMNS, row))
                for k in numeric:
                    d[k] = None if d[k] is None else float(d[k]) if k in h.FIELDS else int(float(d[k]))
                d["last_modified_ts"] = datetime.fromtimestamp(d["last_modified_t"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                tags = d["data_quality_errors_tags"]
                d["data_quality_errors_tags"] = json.loads(tags) if isinstance(tags, str) else (tags or [])
                f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
        print("rows written:", len(rows), "for", len(cards), "keyed products ->", OUT.name)
    finally:
        w.warehouses.stop(wh)
        print("SQL warehouse stop requested")
    return 0


if __name__ == "__main__":
    sys.exit(main())
