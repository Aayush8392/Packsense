"""Measure the privacy bounds on production and write p5_governance/privacy_audit.json. READ-ONLY, counts only. An admin runs it.

  python p5_governance/bootstrap/privacy_audit.py --env-file .env [--dry-run]

--dry-run prints the SQL that would run (no value is involved) and runs nothing. Without it the script runs about six SQL statements on the SQL
warehouse as the admin: row counts, the scrub patterns on bronze, silver and quarantine, one larger query for the known-name bound (it reads the
raw contributor fields inside Databricks and joins them with the kept free text; only integers leave), and the tags dropped. Then render the report:
  python p5_governance/bootstrap/render_privacy_audit.py
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Nothing but integers is printed or stored.
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import privacy_audit_lib as pal  # noqa: E402

DEFAULT_WAREHOUSE = "c9e35ecf0a03295d"      # the Serverless Starter 2X-Small: an address, not a secret


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def make_run(w):
    wh = os.environ.get("DBT_HTTP_PATH", DEFAULT_WAREHOUSE).rstrip("/").split("/")[-1]

    def run(sql: str):
        t0 = time.time()
        r = w.statement_execution.execute_statement(warehouse_id=wh, statement=sql, wait_timeout="50s")
        while r.status.state.value in ("PENDING", "RUNNING"):
            if time.time() - t0 > 1800:
                raise RuntimeError("a statement ran longer than 30 minutes: stopping (nothing is cancelled for you; check the warehouse)")
            time.sleep(5)
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"{r.status.state.value}: {str(r.status.error)[:300]}")
        cols = [c.name for c in r.manifest.schema.columns]
        print(f"  statement finished in {time.time() - t0:.0f}s ({len(cols)} columns)")
        return cols, (r.result.data_array if r.result and r.result.data_array else [])

    return run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)
    t = pal.tables()
    if args.dry_run:
        for name, sql in (("rows", pal.rows_sql(t)), ("patterns bronze", pal.pattern_counts_sql(t, "bronze")),
                          ("known names", pal.known_names_sql(t)), ("tags dropped", pal.tags_dropped_sql(t))):
            print(f"--- {name}\n{sql}\n")
        return 0
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    result = pal.measure(make_run(w), datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
    bad = pal.only_counts(result)
    if bad:
        sys.exit("refusing to store a result that holds more than counts: " + "; ".join(bad[:5]))
    pal.RESULT_PATH.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {pal.RESULT_PATH.name}: {result['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
