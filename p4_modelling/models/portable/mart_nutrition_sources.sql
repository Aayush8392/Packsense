{{ config(materialized='table') }}

-- Where the nutrition numbers come from (roadmap Phase E, the chart gallery). One row per (scope, source) over the input sets of the products we hold
-- (product_nutrition_sets: the latest version of each product, one row per source x preparation x basis). OFF lists a source for each set: printed on the
-- pack, given by the maker, or OFF's own estimate. n_sets counts sets, n_products counts distinct products with at least one set of that source. A product
-- with no input set (legacy nutrition format, or none) has no row here. Counts only.
--   scope  'all' = every product we hold; 'india' = a product that ever had India in a period (the rule of the quality fact and the scorecard).
with india_codes as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

scoped as (
    select 'all' as scope, s.code, s.source from {{ ref('product_nutrition_sets') }} as s
    union all
    select 'india' as scope, s.code, s.source from {{ ref('product_nutrition_sets') }} as s inner join india_codes as i on i.code = s.code
)

select
    {{ dbt.hash(dbt.concat(['scope', "'|'", 'source'])) }} as nutrition_source_key,
    scope,
    source,
    count(*) as n_sets,
    count(distinct code) as n_products
from scoped
group by scope, source
