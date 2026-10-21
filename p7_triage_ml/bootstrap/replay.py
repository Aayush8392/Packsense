"""Prints how many products we held, and how many OFF quality flags were open, at the end of one or more past UTC days. Counts only.

  python p7_triage_ml/bootstrap/replay.py --day 2026-10-05 [--day 2026-10-10 ...] [--env-file .env] [--schema packsense_gold]
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin, which can read gold), set in your own shell; or pass --env-file PATH.
Read-only: one SELECT per day against `workspace.<schema>.product_history` and `product_flag_spans`. It prints no product and no value
(no bulk data on the laptop). The state itself (`replay_lib.state_as_of_sql`) is meant to be read inside Databricks by a consumer.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p7_triage_ml"))
sys.path.insert(0, str(ROOT / "p4_modelling" / "bootstrap"))
import fixture_databricks as fd  # noqa: E402
import replay_lib  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day", action="append", required=True, help="a UTC day, YYYY-MM-DD (repeatable)")
    ap.add_argument("--env-file")
    ap.add_argument("--schema", default="packsense_gold")
    args = ap.parse_args(argv)
    if args.env_file:
        fd.load_env_file(args.env_file)
    w = fd.client()
    print(f"{'day':<12}{'products held':>15}{'open error':>12}{'open warning':>14}{'open info':>11}{'open bug':>10}")
    for day in args.day:
        t = replay_lib.end_of_day_t(day)
        sql = replay_lib.counts_as_of_sql(t, f"workspace.{args.schema}.product_history", f"workspace.{args.schema}.product_flag_spans")
        row = fd.run_sql(w, sql).result.data_array[0]
        print(f"{day:<12}{int(row[0]):>15,}{int(row[1]):>12,}{int(row[2]):>14,}{int(row[3]):>11,}{int(row[4]):>10,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
