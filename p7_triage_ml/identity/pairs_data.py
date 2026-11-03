"""Reads India's products and the candidate pairs from gold into memory (admin token; read-only) and scores them with the baseline in identity_lib.

Candidate pairs: the union of the two blocking keys of measure_blocking_yield.py (brand + food group; brand + a shared category tag held by 2 to 300 products of the market).
Everything stays in memory in the caller; nothing is written here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p4_modelling" / "bootstrap"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_databricks as fd  # noqa: E402
import identity_lib as il  # noqa: E402

MARKET = "en:india"
MAX_TAG = 300


def scope_sql(schema: str, market: str = MARKET) -> str:
    g = f"workspace.{schema}"
    return f"""scope as (
    select code, history_key, brand_key, pnns_groups_2 as grp, product_name, brands, product_quantity as qty, quantity_amount, quantity_unit, energy_kcal, fat, carbohydrates, proteins, salt
    from (select h.*, row_number() over (partition by h.code order by h.period_no desc) rn
          from {g}.product_history h join {g}.bridge_product_market m on m.history_key = h.history_key
          where h.is_latest_observed = 1 and m.market_code = '{market}') where rn = 1)"""


def load(schema: str = "packsense_gold", market: str = MARKET):
    """Returns (products by code, pairs as (code_a, code_b) with code_a < code_b)."""
    w = fd.client()
    run = lambda q: fd.run_sql(w, q).result.data_array  # noqa: E731
    g = f"workspace.{schema}"
    sc = scope_sql(schema, market)
    cols = ["code", "brand_key", "grp", "product_name", "brands", "qty", "quantity_amount", "quantity_unit", "energy_kcal", "fat", "carbohydrates", "proteins", "salt"]
    products = {}
    for r in run(f"with {sc} select {', '.join(cols)} from scope"):
        d = dict(zip(cols, r))
        for k in ("qty", "quantity_amount", "energy_kcal", "fat", "carbohydrates", "proteins", "salt"):
            d[k] = None if d[k] is None else float(d[k])
        products[d["code"]] = d
    pairs_sql = f"""with {sc},
 blockable as (select * from scope where brand_key is not null),
 by_group as (select a.code ca, b.code cb from blockable a join blockable b on a.brand_key = b.brand_key and a.grp = b.grp and a.code < b.code
              where a.grp is not null and a.grp <> 'unknown'),
 tagged as (select s.code, s.brand_key, c.category_tag tag from blockable s join {g}.bridge_product_category c on c.history_key = s.history_key),
 usable as (select tag from tagged group by tag having count(*) between 2 and {MAX_TAG}),
 ct as (select distinct t.code, t.brand_key, t.tag from tagged t join usable u on u.tag = t.tag),
 by_tag as (select a.code ca, b.code cb from ct a join ct b on a.brand_key = b.brand_key and a.tag = b.tag and a.code < b.code)
 select distinct ca, cb from (select * from by_group union all select * from by_tag)"""
    pairs = [(r[0], r[1]) for r in run(pairs_sql)]
    return products, pairs


def score(products: dict, pairs: list[tuple[str, str]]) -> list[dict]:
    names = {c: f"{p['brands'] or ''} {p['product_name'] or ''}" for c, p in products.items()}
    idf = il.idf_table(list(names.values()))
    vec = {c: il.vector(n, idf) for c, n in names.items()}
    out = []
    for a, b in pairs:
        pa, pb = products[a], products[b]
        out.append({"a": a, "b": b, "score": il.cosine(vec[a], vec[b]), "size": il.size_relation(pa["qty"], pb["qty"]), "gap": il.nutrition_gap(pa, pb)})
    return out
