-- Independent check of the two small summary marts behind the chart gallery. (1) mart_rule_checks: per scope and rule, the products checked and flagged must
-- equal the same counts taken a different way from product_rule_verdicts (distinct codes with an ok/violated verdict, and distinct codes with a violated one,
-- instead of the model's per-product maximum). (2) mart_nutrition_sources: per scope, the sets must add up to the rows of product_nutrition_sets, and no
-- source can have more products than sets or more products than the scope holds. A row is returned for every disagreement.
with india as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

verdicts as (
    select 'all' as scope, v.code, v.rule, v.status from {{ ref('product_rule_verdicts') }} as v
    union all
    select 'india' as scope, v.code, v.rule, v.status from {{ ref('product_rule_verdicts') }} as v inner join india as i on i.code = v.code
),

rule_expected as (
    select
        scope,
        rule,
        count(distinct case when status in ('ok', 'violated') then code end) as n_checked,
        count(distinct case when status = 'violated' then code end) as n_flagged
    from verdicts
    group by scope, rule
),

rule_bad as (
    select 'rule ' || g.scope || ' ' || g.rule as what
    from {{ ref('mart_rule_checks') }} as g
    left join rule_expected as e on e.scope = g.scope and e.rule = g.rule
    where e.rule is null or g.n_products_checked <> e.n_checked or g.n_products_flagged <> e.n_flagged
    union all
    select 'rule missing ' || e.scope || ' ' || e.rule
    from rule_expected as e
    left join {{ ref('mart_rule_checks') }} as g on e.scope = g.scope and e.rule = g.rule
    where g.rule is null and e.n_checked > 0
),

source_bad as (
    select 'sets ' || g.scope as what
    from (select scope, sum(n_sets) as sets from {{ ref('mart_nutrition_sources') }} group by scope) as g
    left join (
        select 'all' as scope, count(*) as sets from {{ ref('product_nutrition_sets') }}
        union all
        select 'india' as scope, count(*) as sets from {{ ref('product_nutrition_sets') }} as s inner join india as i on i.code = s.code
    ) as e on e.scope = g.scope
    where e.sets is null or g.sets <> e.sets
    union all
    select 'products ' || scope || ' ' || source from {{ ref('mart_nutrition_sources') }} where n_products > n_sets or n_products < 1
)

select what from rule_bad
union all
select what from source_bad
