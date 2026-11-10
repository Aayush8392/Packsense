"""Read-only count: how many 'nutrition error flag removed after the stored values changed' fixes does production silver hold? (counts only, no rows leave)

  python p8_steward/history_key_count.py --env-file .env

A fix is a step from one silver version of a product to the next where the nutrition error flags go from some to none, the per-100 values change and the new
version is per 100 g. Counted by month of the fixing version, all markets, from silver_product_versions (the capture history since the end of September 2026 plus the India seed).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from history_key_check import FIELDS  # noqa: E402
from history_key_fetch import load_env_file  # noqa: E402


def build_sql() -> str:
    lags = ", ".join(f"lag({f}) over w as p_{f}" for f in FIELDS)
    diffs = " or ".join(f"((p_{f} is null) <> ({f} is null)) or abs({f} - p_{f}) > 1e-6 * greatest(1.0, abs(p_{f}))" for f in FIELDS)
    err = "size(filter(data_quality_errors_tags, t -> t like '%nutrition%'))"
    return f"""
with v as (
  select code, last_modified_t, nutrition_per, {err} as n_err, {", ".join(FIELDS)},
         lag({err}) over w as p_err, {lags}
  from workspace.packsense_silver.silver_product_versions
  window w as (partition by code order by last_modified_t)
), fixes as (
  select code, last_modified_t from v
  where p_err > 0 and n_err = 0 and nutrition_per = '100g' and ({diffs})
)
select date_format(from_unixtime(last_modified_t), 'yyyy-MM') as month, count(*) as fixes, count(distinct code) as products
from fixes group by 1 order by 1
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    load_env_file(ap.parse_args().env_file)
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(name, None)
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    wh = next(iter(w.warehouses.list())).id
    try:
        r = w.statement_execution.execute_statement(warehouse_id=wh, statement=build_sql(), wait_timeout="50s")
        if r.status.state.value != "SUCCEEDED":
            sys.exit(f"query state: {r.status.state.value} {r.status.error.message if r.status.error else ''}")
        for month, fixes, products in r.result.data_array or []:
            print(month, "fixes", fixes, "products", products)
    finally:
        w.warehouses.stop(wh)
        print("SQL warehouse stop requested")
    return 0


if __name__ == "__main__":
    sys.exit(main())
