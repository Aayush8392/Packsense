{{ config(materialized='table') }}

-- Brand scorecard (P4 slice 7, decided 2026-10-18): one row per (scope, brand) describing the products we HOLD as they stood at the end of the
-- newest complete day (as_of_date; macro complete_days). A snapshot rebuilt in full each night, not a history: we hold only a few weeks, so a
-- monthly series starts when a second month exists (P6 can keep month-end copies of this table).
--   scope        'all' = every product we hold; 'india' = a product that ever had India in a period (the rule of the quality fact).
--   brand        the first free-text brand, lower-cased (dim_brand); spelling variants stay separate. Products with no brand form one row,
--                brand_name '(no brand)', never ranked.
--   n_products   products alive on as_of_date (one history period each).
--   n_with_*     field coverage from the product's period: a nutrition table (new or legacy format), a known Nutri-Score (a to e), a NOVA group,
--                a quantity, an ingredients fingerprint, at least one category, at least one label. coverage_points is the sum of the seven
--                counts (7 * n_products would be full coverage); shares are left to the reader, so no float crosses the engines.
--   open_error_spans / open_warning_spans   flag spans open at the end of as_of_date on those products (spans, not products);
--   n_products_with_error_flag              products with at least one open error span.
--   is_ranked    1 when the brand is named and has at least var scorecard_min_products (30) products: a share on fewer is too noisy to rank.
-- This is the quality of what we hold, not of the brand's catalogue: non-India products arrive only if edited since the capture began (dim_market.coverage)
-- and 22k of the India products come from the one-time seed. OFF's own completeness score is not used (it is volatile and untracked).
with bounds as (
    select last_day from {{ complete_days() }} as cd
),

alive as (
    select
        h.code, h.history_key, h.first_brand, h.nutrition_format, h.nutriscore_grade, h.nova_group, h.quantity_amount, h.ingredients_sha256,
        b.last_day as as_of_date
    from {{ ref('product_history') }} as h
    cross join bounds as b
    where {{ epoch_date('h.valid_from_t') }} <= b.last_day
      and (h.valid_to_t is null or {{ epoch_date('h.valid_to_t') }} > b.last_day)
),

open_spans as (
    select
        s.code,
        sum(case when s.severity = 'error' then 1 else 0 end) as open_error_spans,
        sum(case when s.severity = 'warning' then 1 else 0 end) as open_warning_spans
    from {{ ref('product_flag_spans') }} as s
    cross join bounds as b
    where {{ epoch_date('s.first_seen_t') }} <= b.last_day
      and (s.vanished_at_t is null or {{ epoch_date('s.vanished_at_t') }} > b.last_day)
    group by s.code
),

with_categories as (
    select distinct history_key from {{ ref('bridge_product_category') }}
),

with_labels as (
    select distinct history_key from {{ ref('bridge_product_label') }}
),

india_codes as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

per_product as (
    select
        a.code,
        a.first_brand,
        a.as_of_date,
        case when a.nutrition_format in ('new', 'legacy') then 1 else 0 end as has_nutrition,
        case when a.nutriscore_grade in ('a', 'b', 'c', 'd', 'e') then 1 else 0 end as has_nutriscore,
        case when a.nova_group is not null then 1 else 0 end as has_nova,
        case when a.quantity_amount is not null then 1 else 0 end as has_quantity,
        case when a.ingredients_sha256 is not null then 1 else 0 end as has_ingredients,
        case when c.history_key is not null then 1 else 0 end as has_categories,
        case when l.history_key is not null then 1 else 0 end as has_labels,
        coalesce(o.open_error_spans, 0) as open_error_spans,
        coalesce(o.open_warning_spans, 0) as open_warning_spans
    from alive as a
    left join with_categories as c on c.history_key = a.history_key
    left join with_labels as l on l.history_key = a.history_key
    left join open_spans as o on o.code = a.code
),

scoped as (
    select 'all' as scope, p.* from per_product as p
    union all
    select 'india' as scope, p.* from per_product as p inner join india_codes as i on i.code = p.code
),

grouped as (
    select
        scope,
        first_brand,
        max(as_of_date) as as_of_date,
        count(*) as n_products,
        sum(has_nutrition) as n_with_nutrition,
        sum(has_nutriscore) as n_with_nutriscore,
        sum(has_nova) as n_with_nova,
        sum(has_quantity) as n_with_quantity,
        sum(has_ingredients) as n_with_ingredients,
        sum(has_categories) as n_with_categories,
        sum(has_labels) as n_with_labels,
        sum(open_error_spans) as open_error_spans,
        sum(open_warning_spans) as open_warning_spans,
        sum(case when open_error_spans > 0 then 1 else 0 end) as n_products_with_error_flag
    from scoped
    group by scope, first_brand
)

select
    {{ dbt.hash(dbt.concat(['scope', "'|'", "coalesce(first_brand, '')"])) }} as scorecard_key,
    scope,
    {{ dbt.hash('first_brand') }} as brand_key,
    coalesce(first_brand, '(no brand)') as brand_name,
    as_of_date,
    n_products,
    n_with_nutrition,
    n_with_nutriscore,
    n_with_nova,
    n_with_quantity,
    n_with_ingredients,
    n_with_categories,
    n_with_labels,
    n_with_nutrition + n_with_nutriscore + n_with_nova + n_with_quantity + n_with_ingredients + n_with_categories + n_with_labels as coverage_points,
    open_error_spans,
    open_warning_spans,
    n_products_with_error_flag,
    case when first_brand is not null and n_products >= {{ var('scorecard_min_products', 30) }} then 1 else 0 end as is_ranked
from grouped
