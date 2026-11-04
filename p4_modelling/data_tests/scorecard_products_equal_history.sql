-- Independent check of the brand scorecard's population: per scope and CANONICAL brand (item 21c), n_products must equal the products that were alive on as_of_date,
-- counted a different way (the newest period of each product with a start on or before that day, by row_number, not by the interval test the
-- model uses), and the brand rows must add up to the products first seen on or before that day. n_raw_spellings is checked the same way.
with day as (
    select max(as_of_date) as d from {{ ref('mart_brand_scorecard') }}
),

newest as (
    select h.code, h.first_brand,
           row_number() over (partition by h.code order by h.valid_from_t desc) as rn
    from {{ ref('product_history') }} as h cross join day as dd
    where {{ epoch_date('h.valid_from_t') }} <= dd.d
),

india as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

mapped as (
    -- the canonical brand reached by a different join than the model's (hashed raw brand against dim_brand_canonical.brand_key, not the name)
    select n.code, n.rn, n.first_brand as raw_brand, coalesce(bc.canonical_name, n.first_brand) as brand
    from newest as n
    left join {{ ref('dim_brand_canonical') }} as bc on bc.brand_key = {{ dbt.hash('n.first_brand') }}
),

expected as (
    select 'all' as scope, coalesce(brand, '(no brand)') as brand_name, count(*) as n, count(distinct raw_brand) as n_raw
    from mapped where rn = 1 group by coalesce(brand, '(no brand)')
    union all
    select 'india' as scope, coalesce(m.brand, '(no brand)') as brand_name, count(*) as n, count(distinct m.raw_brand) as n_raw
    from mapped as m inner join india as i on i.code = m.code
    where m.rn = 1 group by coalesce(m.brand, '(no brand)')
)

select e.scope, e.brand_name, e.n as expected, coalesce(g.n_products, 0) as got, e.n_raw as expected_raw, g.n_raw_spellings as got_raw
from expected as e
left join {{ ref('mart_brand_scorecard') }} as g on g.scope = e.scope and g.brand_name = e.brand_name
where e.n <> coalesce(g.n_products, 0) or e.n_raw <> coalesce(g.n_raw_spellings, -1)

union all

select g.scope, g.brand_name, 0 as expected, g.n_products as got, 0 as expected_raw, g.n_raw_spellings as got_raw
from {{ ref('mart_brand_scorecard') }} as g
left join expected as e on e.scope = g.scope and e.brand_name = g.brand_name
where e.scope is null
