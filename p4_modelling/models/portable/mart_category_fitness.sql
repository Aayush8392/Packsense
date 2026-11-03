{{ config(materialized='table') }}

-- Category fitness (roadmap Phase D, item 21): one row per (scope, top-level category) describing the products we HOLD as they stood at the end of
-- the newest complete day (as_of_date; macro complete_days). A snapshot rebuilt in full each night, in the shape of mart_brand_scorecard: counts only,
-- the reader computes the shares, so no float crosses the engines. The same definitions as p7_triage_ml/analysis/fitness_for_use.py (a test compares them).
--   scope         'all' = every product we hold; 'india' = a product that ever had India in a period (the rule of the quality fact and the scorecard).
--   category      the FIRST category tag of the product's period (OFF lists the broad category first), or '(no category)'.
--   n_products    products alive on as_of_date (one history period each).
--   n_five_nutrients       products with all five core nutrients (energy in kcal, fat, carbohydrates, proteins, salt).
--   n_with_ingredients     products with an ingredients fingerprint.   n_with_quantity   products with a quantity.
--   n_changed_28d          products with a tracked change that was NOT the seed in the 28 days up to and including as_of_date. For scope 'all' this
--                          is an artefact: outside India a product is held only because it was edited after the capture began, so read it for 'india'.
--   n_stale_365d           products whose last recorded edit (OFF's last-modified time of the period's newest version) is more than 365 days before as_of_date.
--   is_ranked     1 when the category is named and has at least var category_min_products (200) products.
-- Date arithmetic is done on Unix seconds before epoch_date, never on dates, so the two engines cannot differ.
with bounds as (
    select last_day from {{ complete_days() }} as cd
),

alive as (
    select
        h.code, h.categories_tags, h.energy_kcal, h.fat, h.carbohydrates, h.proteins, h.salt, h.quantity_amount, h.ingredients_sha256, h.last_version_t,
        b.last_day as as_of_date
    from {{ ref('product_history') }} as h
    cross join bounds as b
    where {{ epoch_date('h.valid_from_t') }} <= b.last_day
      and (h.valid_to_t is null or {{ epoch_date('h.valid_to_t') }} > b.last_day)
),

changed as (
    select distinct h.code
    from {{ ref('product_history') }} as h
    cross join bounds as b
    where not h.opened_by_seed
      and {{ epoch_date('h.valid_from_t') }} <= b.last_day
      and {{ epoch_date('h.valid_from_t + 28 * 86400') }} > b.last_day
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
        coalesce({{ first_element('a.categories_tags') }}, '(no category)') as category,
        a.as_of_date,
        case when a.energy_kcal is not null and a.fat is not null and a.carbohydrates is not null and a.proteins is not null and a.salt is not null
             then 1 else 0 end as has_five_nutrients,
        case when a.ingredients_sha256 is not null then 1 else 0 end as has_ingredients,
        case when a.quantity_amount is not null then 1 else 0 end as has_quantity,
        case when c.code is not null then 1 else 0 end as changed_28d,
        case when {{ epoch_date('a.last_version_t + 365 * 86400') }} <= a.as_of_date then 1 else 0 end as stale_365d
    from alive as a
    left join changed as c on c.code = a.code
),

scoped as (
    select 'all' as scope, p.* from per_product as p
    union all
    select 'india' as scope, p.* from per_product as p inner join india_codes as i on i.code = p.code
),

grouped as (
    select
        scope,
        category,
        max(as_of_date) as as_of_date,
        count(*) as n_products,
        sum(has_five_nutrients) as n_five_nutrients,
        sum(has_ingredients) as n_with_ingredients,
        sum(has_quantity) as n_with_quantity,
        sum(changed_28d) as n_changed_28d,
        sum(stale_365d) as n_stale_365d
    from scoped
    group by scope, category
)

select
    {{ dbt.hash(dbt.concat(['scope', "'|'", 'category'])) }} as category_fitness_key,
    scope,
    category,
    as_of_date,
    n_products,
    n_five_nutrients,
    n_with_ingredients,
    n_with_quantity,
    n_changed_28d,
    n_stale_365d,
    case when category <> '(no category)' and n_products >= {{ var('category_min_products', 200) }} then 1 else 0 end as is_ranked
from grouped
