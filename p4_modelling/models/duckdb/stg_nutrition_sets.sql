{{ config(materialized='view') }}

-- DuckDB twin of the Databricks view of the same name: `unnest` plays the role of `explode`, and a missing nutrient key gives NULL on both engines
-- (Databricks needs try_element_at for that under ANSI mode; DuckDB's map[key] already does it). A product with no input sets gives no rows.
with latest as (
    select code, last_modified_t, input_sets
    from (
        select code, last_modified_t, input_sets, row_number() over (partition by code order by last_modified_t desc) as rn
        from {{ ref('stg_silver_versions') }}
    )
    where rn = 1
),

exploded as (
    select code, last_modified_t, unnest(input_sets) as s from latest
)

select
    code,
    last_modified_t,
    s.source as source,
    s.preparation as preparation,
    s.per as per,
    s.per_quantity as per_quantity,
    s.per_unit as per_unit,
    cast(coalesce(s.nutrients['energy-kj'].value, s.nutrients['energy'].value) as double) as energy_kj,
    cast(s.nutrients['energy-kcal'].value as double) as energy_kcal,
    {{ grams("s.nutrients['fat']") }} as fat,
    {{ grams("s.nutrients['saturated-fat']") }} as saturated_fat,
    {{ grams("s.nutrients['carbohydrates']") }} as carbohydrates,
    {{ grams("s.nutrients['sugars']") }} as sugars,
    {{ grams("s.nutrients['starch']") }} as starch,
    {{ grams("s.nutrients['fiber']") }} as fiber,
    {{ grams("s.nutrients['proteins']") }} as proteins,
    {{ grams("s.nutrients['salt']") }} as salt,
    {{ grams("s.nutrients['sodium']") }} as sodium
from exploded
