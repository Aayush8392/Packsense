{{ config(materialized='table') }}

-- The 11 nutrition rules of OFF that arithmetic or physics can decide (p7_triage_ml/rules_lib.py is the Python twin; the pytest test_rule_verdicts_agree
-- keeps the two in step), decided for every input set OFF itself checks: a set that is not OFF's own estimate and is given per 100 g or per 100 ml.
-- One row per set and rule, all three statuses kept: 'violated' (with a severity and how far past the limit), 'ok', or 'not_applicable' (an input is missing or
-- the rule does not apply), so 'ok' is never confused with 'could not check'. Rebuilt in full every night. Source of every number: OFF's DataQualityFood.pm and
-- Nutrition.pm. Not applied (they can only make OFF fire LESS than these rules): the '<' and '~' modifiers on a value and OFF's per-category switch for the
-- computed-energy error. deviation is rounded to 4 decimals.
{% set KJ_PER_KCAL_LOW = 3.7 %}{% set KJ_PER_KCAL_HIGH = 4.7 %}{% set KJ_KCAL_SLACK = 2 %}
{% set ENERGY_ERROR_RATIO = 0.30 %}{% set ENERGY_WARNING_RATIO = 0.15 %}{% set ENERGY_SLACK = 5 %}
{% set ENERGY_MIN_KJ = 55 %}{% set ENERGY_MIN_KCAL = 13 %}
{% set SALT_PER_SODIUM = 2.5 %}{% set SALT_SODIUM_TOLERANCE = 0.1 %}
{% set PART_TOLERANCE_SMALL = 0.01 %}{% set PART_TOLERANCE_LARGE = 0.1 %}{% set PART_LARGE_FROM = 10 %}
{% set NUTRIENT_MAX_G = 105 %}{% set TOTAL_MAX_G = 105 %}{% set ENERGY_MAX_KJ = 3911 %}
{% set TRACE_CARBOHYDRATES = 0.5 %}{% set TRACE_FAT = 0.5 %}

with s as (
    select
        code, source, preparation, per, per_quantity,
        energy_kj as kj, energy_kcal as kcal, fat, saturated_fat, carbohydrates, sugars, starch, proteins, salt, sodium, fiber,
        erythritol, alcohol, max_mass_g,
        -- OFF: without the aggregate polyols value, the individual polyols are summed (zero when none is given)
        coalesce(polyols,
                 case when isomalt is null and maltitol is null and sorbitol is null and erythritol is null then 0
                      else coalesce(erythritol, 0) + coalesce(isomalt, 0) + coalesce(maltitol, 0) + coalesce(sorbitol, 0) end) as polyols_eff
    from {{ ref('product_nutrition_sets') }}
    where not is_estimate and per in ('100g', '100ml')
),

e as (
    select
        *,
        case when carbohydrates is null or fat is null or proteins is null then null
             else (carbohydrates - polyols_eff) * 17 + (polyols_eff - coalesce(erythritol, 0)) * 10 + proteins * 17 + fat * 37
                  + coalesce(alcohol, 0) * 29 + coalesce(fiber, 0) * 8 end as computed_kj,
        case when carbohydrates is null or fat is null or proteins is null then null
             else (carbohydrates - polyols_eff) * 4 + (polyols_eff - coalesce(erythritol, 0)) * 2.4 + proteins * 4 + fat * 9
                  + coalesce(alcohol, 0) * 7 + coalesce(fiber, 0) * 2 end as computed_kcal,
        -- a part-of-a-total rule: how far the parts exceed the total (a stated 0 total counts as a trace) and the tolerance that applies; NULL when an input is missing
        case when carbohydrates is null or (sugars is null and starch is null) then null
             else round(round(coalesce(sugars, 0) + coalesce(starch, 0), 2) - round(case when carbohydrates = 0 then {{ TRACE_CARBOHYDRATES }} else carbohydrates end, 2), 6) end as carb_excess,
        case when (case when carbohydrates = 0 then {{ TRACE_CARBOHYDRATES }} else carbohydrates end) >= {{ PART_LARGE_FROM }} then {{ PART_TOLERANCE_LARGE }} else {{ PART_TOLERANCE_SMALL }} end as carb_tolerance,
        case when fat is null or saturated_fat is null then null
             else round(round(saturated_fat, 2) - round(case when fat = 0 then {{ TRACE_FAT }} else fat end, 2), 6) end as fat_excess,
        case when (case when fat = 0 then {{ TRACE_FAT }} else fat end) >= {{ PART_LARGE_FROM }} then {{ PART_TOLERANCE_LARGE }} else {{ PART_TOLERANCE_SMALL }} end as fat_tolerance
    from s
),

r as (
    -- 1 kcal greater than kJ
    select code, source, preparation, per, per_quantity, 'energy-value-in-kcal-greater-than-in-kj' as rule,
        case when kj is null or kcal is null then 'not_applicable' when kcal > kj then 'violated' else 'ok' end as status,
        case when kj is not null and kcal is not null and kcal > kj then 'error' end as severity,
        case when kj is not null and kcal is not null and kcal > kj then round(kcal - kj, 4) end as deviation
    from e

    union all
    -- 2 kcal and kJ reversed
    select code, source, preparation, per, per_quantity, 'energy-value-in-kcal-and-kj-are-reversed',
        case when kj is null or kcal is null then 'not_applicable'
             when kcal > kj and kcal > {{ KJ_PER_KCAL_LOW }} * kj - {{ KJ_KCAL_SLACK }} and kcal < {{ KJ_PER_KCAL_HIGH }} * kj + {{ KJ_KCAL_SLACK }} then 'violated'
             else 'ok' end,
        case when kj is not null and kcal is not null and kcal > kj and kcal > {{ KJ_PER_KCAL_LOW }} * kj - {{ KJ_KCAL_SLACK }}
                  and kcal < {{ KJ_PER_KCAL_HIGH }} * kj + {{ KJ_KCAL_SLACK }} then 'error' end,
        cast(null as double)
    from e

    union all
    -- 3 kcal does not match kJ
    select code, source, preparation, per, per_quantity, 'energy-value-in-kcal-does-not-match-value-in-kj',
        case when kj is null or kcal is null then 'not_applicable'
             when kj < {{ KJ_PER_KCAL_LOW }} * kcal - {{ KJ_KCAL_SLACK }} or kj > {{ KJ_PER_KCAL_HIGH }} * kcal + {{ KJ_KCAL_SLACK }} then 'violated'
             else 'ok' end,
        case when kj is not null and kcal is not null
                  and (kj < {{ KJ_PER_KCAL_LOW }} * kcal - {{ KJ_KCAL_SLACK }} or kj > {{ KJ_PER_KCAL_HIGH }} * kcal + {{ KJ_KCAL_SLACK }}) then 'error' end,
        case when kj is null or kcal is null then null
             when kj < {{ KJ_PER_KCAL_LOW }} * kcal - {{ KJ_KCAL_SLACK }} then round(({{ KJ_PER_KCAL_LOW }} * kcal - {{ KJ_KCAL_SLACK }}) - kj, 4)
             when kj > {{ KJ_PER_KCAL_HIGH }} * kcal + {{ KJ_KCAL_SLACK }} then round(kj - ({{ KJ_PER_KCAL_HIGH }} * kcal + {{ KJ_KCAL_SLACK }}), 4) end
    from e

    union all
    -- 4 kJ does not match the value computed from the other nutrients
    select code, source, preparation, per, per_quantity, 'energy-value-in-kj-does-not-match-value-computed-from-other-nutrients',
        case when kj is null or computed_kj is null then 'not_applicable'
             when kj <= {{ ENERGY_MIN_KJ }} and computed_kj <= {{ ENERGY_MIN_KJ }} then 'not_applicable'
             when computed_kj < kj * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }} or computed_kj > kj * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }} then 'violated'
             else 'ok' end,
        case when kj is null or computed_kj is null or (kj <= {{ ENERGY_MIN_KJ }} and computed_kj <= {{ ENERGY_MIN_KJ }}) then null
             when computed_kj < kj * (1 - {{ ENERGY_ERROR_RATIO }}) - {{ ENERGY_SLACK }} or computed_kj > kj * (1 + {{ ENERGY_ERROR_RATIO }}) + {{ ENERGY_SLACK }} then 'error'
             when computed_kj < kj * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }} or computed_kj > kj * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }} then 'warning' end,
        case when kj is null or computed_kj is null or (kj <= {{ ENERGY_MIN_KJ }} and computed_kj <= {{ ENERGY_MIN_KJ }}) then null
             when computed_kj < kj * (1 - {{ ENERGY_ERROR_RATIO }}) - {{ ENERGY_SLACK }} then round((kj * (1 - {{ ENERGY_ERROR_RATIO }}) - {{ ENERGY_SLACK }}) - computed_kj, 4)
             when computed_kj > kj * (1 + {{ ENERGY_ERROR_RATIO }}) + {{ ENERGY_SLACK }} then round(computed_kj - (kj * (1 + {{ ENERGY_ERROR_RATIO }}) + {{ ENERGY_SLACK }}), 4)
             when computed_kj < kj * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }} then round((kj * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }}) - computed_kj, 4)
             when computed_kj > kj * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }} then round(computed_kj - (kj * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }}), 4) end
    from e

    union all
    -- 5 kcal does not match the value computed from the other nutrients
    select code, source, preparation, per, per_quantity, 'energy-value-in-kcal-does-not-match-value-computed-from-other-nutrients',
        case when kcal is null or computed_kcal is null then 'not_applicable'
             when kcal <= {{ ENERGY_MIN_KCAL }} and computed_kcal <= {{ ENERGY_MIN_KCAL }} then 'not_applicable'
             when computed_kcal < kcal * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }} or computed_kcal > kcal * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }} then 'violated'
             else 'ok' end,
        case when kcal is null or computed_kcal is null or (kcal <= {{ ENERGY_MIN_KCAL }} and computed_kcal <= {{ ENERGY_MIN_KCAL }}) then null
             when computed_kcal < kcal * (1 - {{ ENERGY_ERROR_RATIO }}) - {{ ENERGY_SLACK }} or computed_kcal > kcal * (1 + {{ ENERGY_ERROR_RATIO }}) + {{ ENERGY_SLACK }} then 'error'
             when computed_kcal < kcal * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }} or computed_kcal > kcal * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }} then 'warning' end,
        case when kcal is null or computed_kcal is null or (kcal <= {{ ENERGY_MIN_KCAL }} and computed_kcal <= {{ ENERGY_MIN_KCAL }}) then null
             when computed_kcal < kcal * (1 - {{ ENERGY_ERROR_RATIO }}) - {{ ENERGY_SLACK }} then round((kcal * (1 - {{ ENERGY_ERROR_RATIO }}) - {{ ENERGY_SLACK }}) - computed_kcal, 4)
             when computed_kcal > kcal * (1 + {{ ENERGY_ERROR_RATIO }}) + {{ ENERGY_SLACK }} then round(computed_kcal - (kcal * (1 + {{ ENERGY_ERROR_RATIO }}) + {{ ENERGY_SLACK }}), 4)
             when computed_kcal < kcal * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }} then round((kcal * (1 - {{ ENERGY_WARNING_RATIO }}) - {{ ENERGY_SLACK }}) - computed_kcal, 4)
             when computed_kcal > kcal * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }} then round(computed_kcal - (kcal * (1 + {{ ENERGY_WARNING_RATIO }}) + {{ ENERGY_SLACK }}), 4) end
    from e

    union all
    -- 6 energy over 3,911 kJ
    select code, source, preparation, per, per_quantity, 'value-over-3911-energy',
        case when kj is null then 'not_applicable' when kj > {{ ENERGY_MAX_KJ }} then 'violated' else 'ok' end,
        case when kj > {{ ENERGY_MAX_KJ }} then 'error' end,
        case when kj > {{ ENERGY_MAX_KJ }} then round(kj - {{ ENERGY_MAX_KJ }}, 4) end
    from e

    union all
    -- 7 salt does not match sodium (the gap is rounded so float noise cannot tip a gap of exactly 0.1)
    select code, source, preparation, per, per_quantity, 'salt-does-not-match-sodium',
        case when salt is null or sodium is null then 'not_applicable'
             when round(abs(sodium * {{ SALT_PER_SODIUM }} - salt), 6) > {{ SALT_SODIUM_TOLERANCE }} then 'violated' else 'ok' end,
        case when salt is not null and sodium is not null and round(abs(sodium * {{ SALT_PER_SODIUM }} - salt), 6) > {{ SALT_SODIUM_TOLERANCE }} then 'error' end,
        case when salt is not null and sodium is not null and round(abs(sodium * {{ SALT_PER_SODIUM }} - salt), 6) > {{ SALT_SODIUM_TOLERANCE }}
             then round(round(abs(sodium * {{ SALT_PER_SODIUM }} - salt), 6) - {{ SALT_SODIUM_TOLERANCE }}, 4) end
    from e

    union all
    -- 8 sugars plus starch greater than carbohydrates
    select code, source, preparation, per, per_quantity, 'sugars-plus-starch-greater-than-carbohydrates',
        case when carb_excess is null then 'not_applicable' when carb_excess > carb_tolerance then 'violated' else 'ok' end,
        case when carb_excess > carb_tolerance then 'error' end,
        case when carb_excess > carb_tolerance then round(carb_excess - carb_tolerance, 4) end
    from e

    union all
    -- 9 saturated fat greater than fat
    select code, source, preparation, per, per_quantity, 'saturated-fat-greater-than-fat',
        case when fat_excess is null then 'not_applicable' when fat_excess > fat_tolerance then 'violated' else 'ok' end,
        case when fat_excess > fat_tolerance then 'error' end,
        case when fat_excess > fat_tolerance then round(fat_excess - fat_tolerance, 4) end
    from e

    union all
    -- 10 any mass-valued nutrient over 105 g per 100
    select code, source, preparation, per, per_quantity, 'value-over-105',
        case when max_mass_g is null then 'not_applicable' when max_mass_g > {{ NUTRIENT_MAX_G }} then 'violated' else 'ok' end,
        case when max_mass_g > {{ NUTRIENT_MAX_G }} then 'error' end,
        case when max_mass_g > {{ NUTRIENT_MAX_G }} then round(max_mass_g - {{ NUTRIENT_MAX_G }}, 4) end
    from e

    union all
    -- 11 fat + carbohydrates + proteins + salt over 105 g
    select code, source, preparation, per, per_quantity, 'value-total-over-105',
        case when fat is null and carbohydrates is null and proteins is null and salt is null then 'not_applicable'
             when coalesce(fat, 0) + coalesce(carbohydrates, 0) + coalesce(proteins, 0) + coalesce(salt, 0) > {{ TOTAL_MAX_G }} then 'violated' else 'ok' end,
        case when coalesce(fat, 0) + coalesce(carbohydrates, 0) + coalesce(proteins, 0) + coalesce(salt, 0) > {{ TOTAL_MAX_G }}
                  and not (fat is null and carbohydrates is null and proteins is null and salt is null) then 'error' end,
        case when coalesce(fat, 0) + coalesce(carbohydrates, 0) + coalesce(proteins, 0) + coalesce(salt, 0) > {{ TOTAL_MAX_G }}
                  and not (fat is null and carbohydrates is null and proteins is null and salt is null)
             then round(coalesce(fat, 0) + coalesce(carbohydrates, 0) + coalesce(proteins, 0) + coalesce(salt, 0) - {{ TOTAL_MAX_G }}, 4) end
    from e
)

select code, source, preparation, per, per_quantity, rule, status, severity, deviation
from r
