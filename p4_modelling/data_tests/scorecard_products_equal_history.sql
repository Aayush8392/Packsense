-- Independent check of the brand scorecard's population: per scope and brand, n_products must equal the products that were alive on as_of_date,
-- counted a different way (the newest period of each product with a start on or before that day, by row_number, not by the interval test the
-- model uses), and the brand rows must add up to the products first seen on or before that day.
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

expected as (
    select 'all' as scope, coalesce(first_brand, '(no brand)') as brand_name, count(*) as n
    from newest where rn = 1 group by coalesce(first_brand, '(no brand)')
    union all
    select 'india' as scope, coalesce(n.first_brand, '(no brand)') as brand_name, count(*) as n
    from newest as n inner join india as i on i.code = n.code
    where n.rn = 1 group by coalesce(n.first_brand, '(no brand)')
)

select e.scope, e.brand_name, e.n as expected, coalesce(g.n_products, 0) as got
from expected as e
left join {{ ref('mart_brand_scorecard') }} as g on g.scope = e.scope and g.brand_name = e.brand_name
where e.n <> coalesce(g.n_products, 0)

union all

select g.scope, g.brand_name, 0 as expected, g.n_products as got
from {{ ref('mart_brand_scorecard') }} as g
left join expected as e on e.scope = g.scope and e.brand_name = g.brand_name
where e.scope is null
