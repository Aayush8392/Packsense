{{ config(materialized='view') }}

-- One row per input set (one per nutrition source, preparation and basis) of each product's LATEST version. Databricks-only: the explode and the
-- map lookup are engine-specific; try_element_at gives NULL for a nutrient the set does not carry (a plain lookup throws under ANSI mode).
-- A product with no input sets (legacy nutrition format, or none) gives no rows. `energy` is OFF's older key for kJ, used when `energy-kj` is absent.
with latest as (
    select code, last_modified_t, input_sets
    from (
        select code, last_modified_t, input_sets, row_number() over (partition by code order by last_modified_t desc) as rn
        from {{ ref('stg_silver_versions') }}
    )
    where rn = 1
)

select
    l.code,
    l.last_modified_t,
    s.source as source,
    s.preparation as preparation,
    s.per as per,
    s.per_quantity as per_quantity,
    s.per_unit as per_unit,
    cast(coalesce(try_element_at(s.nutrients, 'energy-kj').value, try_element_at(s.nutrients, 'energy').value) as double) as energy_kj,
    cast(try_element_at(s.nutrients, 'energy-kcal').value as double) as energy_kcal,
    {{ grams("try_element_at(s.nutrients, 'fat')") }} as fat,
    {{ grams("try_element_at(s.nutrients, 'saturated-fat')") }} as saturated_fat,
    {{ grams("try_element_at(s.nutrients, 'carbohydrates')") }} as carbohydrates,
    {{ grams("try_element_at(s.nutrients, 'sugars')") }} as sugars,
    {{ grams("try_element_at(s.nutrients, 'starch')") }} as starch,
    {{ grams("try_element_at(s.nutrients, 'fiber')") }} as fiber,
    {{ grams("try_element_at(s.nutrients, 'proteins')") }} as proteins,
    {{ grams("try_element_at(s.nutrients, 'salt')") }} as salt,
    {{ grams("try_element_at(s.nutrients, 'sodium')") }} as sodium,
    {{ grams("try_element_at(s.nutrients, 'polyols')") }} as polyols,
    {{ grams("try_element_at(s.nutrients, 'erythritol')") }} as erythritol,
    {{ grams("try_element_at(s.nutrients, 'isomalt')") }} as isomalt,
    {{ grams("try_element_at(s.nutrients, 'maltitol')") }} as maltitol,
    {{ grams("try_element_at(s.nutrients, 'sorbitol')") }} as sorbitol,
    cast(try_element_at(s.nutrients, 'alcohol').value as double) as alcohol,
    aggregate(
        filter(map_entries(s.nutrients), e -> e.key not like 'energy%'),
        cast(null as double),
        (acc, e) -> greatest(acc, {{ grams("e.value") }})
    ) as max_mass_g
from latest as l
lateral view explode(l.input_sets) x as s
