{{ config(materialized='table') }}

-- The per-source nutrition of each product's latest version: one row per input set (source x preparation x basis). OFF runs its arithmetic checks on each
-- of these sets (estimates excluded), whereas the aggregated nutrient columns in silver mix values from several sets; the rule verdicts and the
-- source-disagreement detector therefore read this table. Current version only, rebuilt in full every night. A product without input sets (legacy
-- nutrition format or none) has no rows. Only the core nutrients the rules need are typed columns; the full nutrient map stays in silver.
--   is_estimate  the set is OFF's own estimate, not something printed on the pack or given by the maker; OFF leaves estimates out of its checks
select
    code,
    last_modified_t,
    source,
    preparation,
    per,
    per_quantity,
    per_unit,
    source = 'estimate' as is_estimate,
    energy_kj,
    energy_kcal,
    fat,
    saturated_fat,
    carbohydrates,
    sugars,
    starch,
    fiber,
    proteins,
    salt,
    sodium
from {{ ref('stg_nutrition_sets') }}
