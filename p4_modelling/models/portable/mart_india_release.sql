{{ config(materialized='table') }}

-- India release mart (Phase B item 11, decided 2026-10-22): one row per India product as we last observed it, the input of the monthly India
-- release (p6_serving/release_lib.py). Nothing here is published by itself: the release job reads this table as the admin, runs the exit function
-- (scrub, catalogue-wide ordinary words, residue scan) and the licence gate on the rendered files, and only then uploads.
--   India       a product whose latest period lists the canonical India tag (dim_market.is_target_market = 1); the rule of the other marts is "ever had
--               India in a period", but a release describes the product as it stands, so the LATEST period decides.
--   one period  the latest observed period of the product (product_history.is_latest_observed = 1); the open row, never a guess about OFF today.
--   excluded    products OFF told us are gone: product_status 'confirmed_not_found' (deleted) or 'moved_other_type' (now in another Open * Facts
--               database). 'unverified', 'present_in_snapshot', 'confirmed_exists', 'invalid_code' and 'unconfirmed' stay; the status is exported.
--   columns     only what the licence rule allows: no image, no ingredient text (silver keeps only its fingerprint), no hashed contributor code,
--               no editor count. Tag lists stay arrays here; the release renders them joined by '|'.
--   open flags  the flags OFF's own checks recorded and that are still open at the latest observation, by severity (counts, not names).
with latest as (
    select * from {{ ref('product_history') }} where is_latest_observed = 1
),

india as (
    select h.code
    from latest as h
    inner join {{ ref('bridge_product_market') }} as b on b.history_key = h.history_key
    inner join {{ ref('dim_market') }} as m on m.market_code = b.market_code
    where m.is_target_market = 1
    group by h.code
),

open_flags as (
    select
        code,
        sum(case when severity = 'error' then 1 else 0 end) as open_error_flags,
        sum(case when severity = 'warning' then 1 else 0 end) as open_warning_flags,
        sum(case when severity = 'info' then 1 else 0 end) as open_info_flags
    from {{ ref('product_flag_spans') }}
    where vanished_at_t is null
    group by code
)

select
    h.code,
    h.product_name,
    h.brands,
    h.quantity_amount,
    h.quantity_unit,
    h.product_quantity,
    h.product_quantity_unit,
    h.serving_amount,
    h.serving_unit,
    h.pnns_groups_1,
    h.pnns_groups_2,
    h.nutrition_format,
    h.nutrition_per,
    h.nutrition_preparation,
    h.energy_kj,
    h.energy_kcal,
    h.fat,
    h.saturated_fat,
    h.carbohydrates,
    h.sugars,
    h.fiber,
    h.proteins,
    h.salt,
    h.sodium,
    h.nutriscore_grade,
    h.nova_group,
    h.environmental_score_grade,
    h.categories_tags,
    h.labels_tags,
    h.allergens_tags,
    h.traces_tags,
    coalesce(f.open_error_flags, 0) as open_error_flags,
    coalesce(f.open_warning_flags, 0) as open_warning_flags,
    coalesce(f.open_info_flags, 0) as open_info_flags,
    s.status as existence_status,
    h.last_version_t as last_modified_t
from latest as h
inner join india as i on i.code = h.code
inner join {{ ref('product_status') }} as s on s.code = h.code
left join open_flags as f on f.code = h.code
where s.status not in ('confirmed_not_found', 'moved_other_type')
