r"""Fitness-for-use report per top-level category (roadmap Phase D item 21). Counts and shares only, read-only on gold.

  .venv\Scripts\python.exe p7_triage_ml\analysis\fitness_for_use.py --env-file .env [--min-products 200] [--market en:india | --all-markets]
Admin, read-only. For each top-level category (the first category tag of the product's newest period) over the products we HOLD (latest observed period):
  completeness  share with all five core nutrients (energy kcal, fat, carbohydrates, proteins, salt), share with an ingredients fingerprint, share with a quantity
  stability     share of products with a tracked change in the last 28 days (a period that did not open as the seed, opened in the last 28 days): lower is steadier
  freshness     median days since the product's last recorded edit (OFF's last-modified time of its newest period)
The history we hold starts at the capture (30 Sep), so stability describes about a month, and the seed products (22k of India's) only show edits made since. IMPORTANT: outside India a product is held only because it was edited after the capture began, so for `--all-markets` the stability column is an artefact (about 76% 'changed') and is printed
with a warning; the default is India, where 22k products come from the one-time seed and stability means something. A total row is printed and the
category rows are checked to add up to it. Prints no product and no barcode.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "p4_modelling" / "bootstrap"))
import fixture_databricks as fd  # noqa: E402

NUTRIENTS = ("energy_kcal", "fat", "carbohydrates", "proteins", "salt")


def report_sql(schema: str = "packsense_gold", market: str | None = None, days: int = 28) -> str:
    g = f"workspace.{schema}"
    market_join = (f"join {g}.bridge_product_market m on m.history_key = h.history_key and m.market_code = '{market}'" if market else "")
    five = " and ".join(f"h.{n} is not null" for n in NUTRIENTS)
    return f"""
with held as (
    select h.code, coalesce(get(h.categories_tags, 0), '(no category)') cat,
           case when {five} then 1 else 0 end five_nutrients,
           case when h.ingredients_sha256 is not null then 1 else 0 end has_ingredients,
           case when h.quantity_amount is not null then 1 else 0 end has_quantity,
           datediff(current_date(), cast(from_unixtime(h.last_version_t) as date)) days_since_edit
    from {g}.product_history h {market_join}
    where h.is_latest_observed = 1
),
changed as (
    select distinct p.code from {g}.product_history p
    where p.opened_by_seed = false and p.valid_from >= date_sub(current_date(), {days})
),
joined as (select h.*, case when c.code is not null then 1 else 0 end changed from held h left join changed c on c.code = h.code)
select cat, count(*) n, sum(five_nutrients), sum(has_ingredients), sum(has_quantity), sum(changed), percentile_approx(days_since_edit, 0.5)
from joined group by cat
""".strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--schema", default="packsense_gold")
    ap.add_argument("--market", default="en:india")
    ap.add_argument("--all-markets", action="store_true")
    ap.add_argument("--min-products", type=int, default=200)
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args(argv)
    if a.env_file:
        fd.load_env_file(a.env_file)
    w = fd.client()
    if a.all_markets:
        a.market = None
        print("WARNING: outside India a product is held only because it was edited after the capture began: the 'changed' column is an artefact here, not a stability figure.")
    rows = [(r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]), int(r[6])) for r in fd.run_sql(w, report_sql(a.schema, a.market, a.days)).result.data_array]
    total = [sum(r[i] for r in rows) for i in range(1, 6)]
    print(f"products held{' in ' + a.market if a.market else ''}: {total[0]}; with all five nutrients {total[1] / total[0]:.1%}; with ingredients {total[2] / total[0]:.1%}; "
          f"with a quantity {total[3] / total[0]:.1%}; changed in the last {a.days} days {total[4] / total[0]:.1%}")
    print(f"\n{'top category':<46}{'products':>9}{'5 nutr.':>8}{'ingred.':>8}{'qty':>7}{'changed':>9}{'median days since edit':>24}")
    shown = small = 0
    for cat, n, five, ing, qty, ch, med in sorted(rows, key=lambda r: -r[1]):
        if n < a.min_products:
            small += n
            continue
        print(f"{cat[:45]:<46}{n:>9}{five / n:>8.1%}{ing / n:>8.1%}{qty / n:>7.1%}{ch / n:>9.1%}{med:>24}")
        shown += n
    print(f"({len(rows)} categories; categories with fewer than {a.min_products} products hold {small} products and are not listed; listed + not listed = {shown + small}, held = {total[0]})")
    assert shown + small == total[0]
    return 0


if __name__ == "__main__":
    sys.exit(main())
