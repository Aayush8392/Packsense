"""Item 15, step 1: which daily signals does the story engine really have? Read-only, counts only (no product, no username, no value of a product).

    python p8_steward/bootstrap/signal_inventory.py --env-file .env [--out p8_steward/data/signal_days.csv]

Reads the gold daily facts (`fct_product_change_daily`, `fct_catalogue_quality_daily`) and the alert table of the drift monitor (`silver_drift_report`), prints
what columns and days exist, and writes one small derived file of daily aggregates (one row per complete day and scope) for the event finder.
Environment: DATABRICKS_HOST and DATABRICKS_TOKEN (admin), or --env-file, as in p7_triage_ml/bootstrap/replay.py.
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p4_modelling" / "bootstrap"))
import fixture_databricks as fd  # noqa: E402

GOLD = "workspace.packsense_gold"
SILVER = "workspace.packsense_silver"


def rows(w, sql):
    r = fd.run_sql(w, sql).result
    return r.data_array or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env-file")
    ap.add_argument("--out", default=str(ROOT / "p8_steward" / "data" / "signal_days.csv"))
    ap.add_argument("--drift-out", default=str(ROOT / "p8_steward" / "data" / "drift_events.csv"))
    ap.add_argument("--quality-out", default=str(ROOT / "p8_steward" / "data" / "quality_days.csv"))
    ap.add_argument("--through", default="2026-10-23", help="last day kept in the quality file (the trial data stops here so its results stay comparable)")
    args = ap.parse_args(argv)
    if args.env_file:
        fd.load_env_file(args.env_file)
    w = fd.client()

    for t in ("fct_product_change_daily", "fct_catalogue_quality_daily", "mart_brand_scorecard"):
        cols = [r[0] for r in rows(w, f"DESCRIBE {GOLD}.{t}") if r[0] and not r[0].startswith("#")]
        n = rows(w, f"SELECT count(*) FROM {GOLD}.{t}")[0][0]
        print(f"{t}: {n} rows; columns: {', '.join(cols)}")

    change = rows(w, f"""
        SELECT change_date, scope,
               max(CASE WHEN change_group = 'any' THEN n_products END) AS any_products,
               max(CASE WHEN change_group = 'new_product' THEN n_products END) AS new_products,
               max(CASE WHEN change_group = 'any' THEN unseen_edits END) AS unseen_edits,
               max(CASE WHEN change_group = 'nutrition' THEN n_products END) AS nutrition_products,
               max(CASE WHEN change_group = 'ingredients' THEN n_products END) AS ingredients_products
        FROM {GOLD}.fct_product_change_daily
        WHERE opened_by_seed = 0
        GROUP BY change_date, scope ORDER BY change_date, scope""")
    print(f"change fact: {len(change)} day-scope rows, {len({r[0] for r in change})} days, from {change[0][0] if change else '-'} to {change[-1][0] if change else '-'}")

    drift = rows(w, f"SELECT level, check_name, count(*) FROM {SILVER}.silver_drift_report GROUP BY level, check_name ORDER BY level, check_name")
    print(f"drift report: {sum(int(r[2]) for r in drift)} rows in {len(drift)} (level, check) groups")
    for r in drift[:25]:
        print(f"  {r[0]:<8}{r[1]:<48}{r[2]:>6}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["change_date", "scope", "any_products", "new_products", "unseen_edits", "nutrition_products", "ingredients_products"])
        wr.writerows(change)
    print(f"wrote {len(change)} rows to {args.out}")

    events = rows(w, f"""
        SELECT subject, level, check_name, observed, baseline_low, baseline_high, substr(detail, 1, 300)
        FROM {SILVER}.silver_drift_report WHERE level IN ('ALERT', 'WARN') ORDER BY subject, check_name""")
    with open(args.drift_out, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["subject", "level", "check_name", "observed", "baseline_low", "baseline_high", "detail"])
        wr.writerows(events)
    print(f"wrote {len(events)} drift alert and warning rows to {args.drift_out}")

    quality = rows(w, f"""
        SELECT snapshot_date, scope, sum(open_spans), sum(opened_on_known_product), sum(carried_in), sum(vanished), max(n_products_held)
        FROM {GOLD}.fct_catalogue_quality_daily WHERE snapshot_date <= '{args.through}'
        GROUP BY snapshot_date, scope ORDER BY snapshot_date, scope""")
    with open(args.quality_out, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["snapshot_date", "scope", "open_spans", "opened_on_known", "carried_in", "vanished", "products_held"])
        wr.writerows(quality)
    print(f"wrote {len(quality)} quality day rows to {args.quality_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
