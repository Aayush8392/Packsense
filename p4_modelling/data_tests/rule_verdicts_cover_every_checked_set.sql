-- Every set OFF checks (not an estimate, per 100 g or 100 ml) has exactly one verdict per rule: 11 rows, no more and no fewer, and no verdict for any other set.
with expected as (
    select code, source, preparation, per, per_quantity
    from {{ ref('product_nutrition_sets') }}
    where not is_estimate and per in ('100g', '100ml')
),
got as (
    select code, source, preparation, per, per_quantity, count(*) as n, count(distinct rule) as n_rules
    from {{ ref('product_rule_verdicts') }}
    group by code, source, preparation, per, per_quantity
)
select coalesce(g.code, e.code) as code, g.n, g.n_rules
from got as g
full outer join expected as e
    on g.code = e.code and g.source is not distinct from e.source and g.preparation is not distinct from e.preparation
       and g.per is not distinct from e.per and g.per_quantity is not distinct from e.per_quantity
where e.code is null or g.code is null or g.n <> 11 or g.n_rules <> 11
