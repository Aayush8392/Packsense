{{ config(materialized='table') }}

-- Which of OFF's 11 arithmetic checks flag the most products (roadmap Phase E, the chart gallery). One row per (scope, rule) over the products we hold, from
-- product_rule_verdicts (every input set OFF itself checks, latest version of each product). A product counts once per rule however many sets it has:
-- it is 'checked' when at least one of its sets could be decided for that rule (status ok or violated; not_applicable is left out) and 'flagged' when any
-- of its sets violates it. Counts only, the reader computes the share. 'Flagged' is not 'wrong': a rule can fire on a pack that prints something odd.
--   scope  'all' = every product we hold; 'india' = a product that ever had India in a period (the rule of the quality fact and the scorecard).
with per_product as (
    select
        code,
        rule,
        max(case when status = 'violated' then 1 else 0 end) as flagged
    from {{ ref('product_rule_verdicts') }}
    where status in ('ok', 'violated')
    group by code, rule
),

india_codes as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

scoped as (
    select 'all' as scope, p.* from per_product as p
    union all
    select 'india' as scope, p.* from per_product as p inner join india_codes as i on i.code = p.code
)

select
    {{ dbt.hash(dbt.concat(['scope', "'|'", 'rule'])) }} as rule_check_key,
    scope,
    rule,
    count(*) as n_products_checked,
    sum(flagged) as n_products_flagged
from scoped
group by scope, rule
