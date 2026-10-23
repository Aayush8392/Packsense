{{ config(materialized='table') }}

-- The product card (roadmap Phase B item 12; decided 2026-10-23, context amendments A49 and A87): one row per product we hold, DERIVED FACTS ONLY, no product text.
-- It feeds the barcode lookup on the public site (shards by barcode prefix; the size is measured before they are built). Rebuilt in full every night.
--   existence_status   product_status.status: unverified, present_in_snapshot, confirmed_exists, confirmed_not_found, moved_other_type, invalid_code, unconfirmed.
--                      Products OFF has removed or moved stay here on purpose, so the card can say so. `unverified` never means 'exists'.
--   off_error, off_bug, off_warning, off_info
--                      OFF's own quality flags still open on the product's latest version we hold, as counts of flag spans (one open span per flag).
--   rules_checkable    how many of our 11 arithmetic rules (product_rule_verdicts) could be applied on at least one of the product's input sets (0 to 11);
--                      0 when the product has no per-source nutrition table, so nothing of ours can be checked.
--   rules_failed       how many of the 11 rules are violated on at least one input set; rules_failed_error counts those violated at error severity.
--   has_*, fields_filled
--                      the seven fields of the brand scorecard (nutrition table, Nutri-Score a to e, NOVA group, quantity, ingredients fingerprint, a category,
--                      a label) on the latest period, and how many of the seven are filled.
--   versions_kept, last_edit_t, first_version_edited_t, first_period_from_seed
--                      every silver version we hold for it, the time of the newest edit we saw, the OFF edit time of the first version we hold (never 'created
--                      on': for a product that came from the one-time dump this is simply its last edit before the dump).
--   in_india           the product ever had India in a period (the rule of the scorecard and the quality fact).
--   things_flagged     OFF error + OFF bug flags + our failed rules. Warnings and info flags are NOT counted: about nine flags are open on an average product and two
--                      families make up about four in five of them, so counting them would colour nearly every product.
--   light              a CODE for the card's signal, decided 2026-10-23 (the words and colours belong to the app, so they can change without touching the data):
--                      several_flagged (things_flagged >= var card_several_from, default 2), one_flagged (1), not_enough_data (nothing flagged and rules_checkable = 0:
--                      none of our checks could run), none_flagged (nothing flagged and at least one of our checks ran). none_flagged never means correct.
with latest as (
    select * from {{ ref('product_history') }} where is_latest_observed = 1
),

whole_history as (
    select
        code,
        sum(versions_merged) as versions_kept,
        max(last_version_t) as last_edit_t,
        min(valid_from_t) as first_version_edited_t,
        max(case when period_no = 1 and opened_by_seed then 1 else 0 end) as first_period_from_seed
    from {{ ref('product_history') }}
    group by code
),

off_flags as (
    select
        code,
        sum(case when severity = 'error' then 1 else 0 end) as off_error,
        sum(case when severity = 'bug' then 1 else 0 end) as off_bug,
        sum(case when severity = 'warning' then 1 else 0 end) as off_warning,
        sum(case when severity = 'info' then 1 else 0 end) as off_info
    from {{ ref('product_flag_spans') }}
    where is_open = 1
    group by code
),

our_rules as (
    select
        code,
        count(distinct case when status <> 'not_applicable' then rule end) as rules_checkable,
        count(distinct case when status = 'violated' then rule end) as rules_failed,
        count(distinct case when status = 'violated' and severity = 'error' then rule end) as rules_failed_error
    from {{ ref('product_rule_verdicts') }}
    group by code
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

card as (
    select
        l.code,
        s.status as existence_status,
        coalesce(f.off_error, 0) as off_error,
        coalesce(f.off_bug, 0) as off_bug,
        coalesce(f.off_warning, 0) as off_warning,
        coalesce(f.off_info, 0) as off_info,
        coalesce(r.rules_checkable, 0) as rules_checkable,
        coalesce(r.rules_failed, 0) as rules_failed,
        coalesce(r.rules_failed_error, 0) as rules_failed_error,
        case when l.nutrition_format in ('new', 'legacy') then 1 else 0 end as has_nutrition,
        case when l.nutriscore_grade in ('a', 'b', 'c', 'd', 'e') then 1 else 0 end as has_nutriscore,
        case when l.nova_group is not null then 1 else 0 end as has_nova,
        case when l.quantity_amount is not null then 1 else 0 end as has_quantity,
        case when l.ingredients_sha256 is not null then 1 else 0 end as has_ingredients,
        case when c.history_key is not null then 1 else 0 end as has_categories,
        case when lb.history_key is not null then 1 else 0 end as has_labels,
        h.versions_kept,
        h.last_edit_t,
        h.first_version_edited_t,
        h.first_period_from_seed,
        case when i.code is not null then 1 else 0 end as in_india
    from latest as l
    inner join whole_history as h on h.code = l.code
    inner join {{ ref('product_status') }} as s on s.code = l.code
    left join off_flags as f on f.code = l.code
    left join our_rules as r on r.code = l.code
    left join with_categories as c on c.history_key = l.history_key
    left join with_labels as lb on lb.history_key = l.history_key
    left join india_codes as i on i.code = l.code
)

select
    code,
    existence_status,
    case
        when off_error + off_bug + rules_failed >= {{ var('card_several_from', 2) }} then 'several_flagged'
        when off_error + off_bug + rules_failed >= 1 then 'one_flagged'
        when rules_checkable = 0 then 'not_enough_data'
        else 'none_flagged'
    end as light,
    off_error + off_bug + rules_failed as things_flagged,
    off_error,
    off_bug,
    off_warning,
    off_info,
    rules_checkable,
    rules_failed,
    rules_failed_error,
    has_nutrition,
    has_nutriscore,
    has_nova,
    has_quantity,
    has_ingredients,
    has_categories,
    has_labels,
    has_nutrition + has_nutriscore + has_nova + has_quantity + has_ingredients + has_categories + has_labels as fields_filled,
    versions_kept,
    last_edit_t,
    first_version_edited_t,
    first_period_from_seed,
    in_india
from card
