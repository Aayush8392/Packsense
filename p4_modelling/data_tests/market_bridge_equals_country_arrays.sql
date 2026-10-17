-- Databricks-only (array sizes): the bridge holds one row per distinct country tag of every period, nothing lost or doubled.
select bridge.n_rows, arrays.n_tags
from (select count(*) as n_rows from {{ ref('bridge_product_market') }}) as bridge
cross join (
    select sum(case when countries_tags is null then 0 else size(array_distinct(countries_tags)) end) as n_tags
    from {{ ref('product_history') }}
) as arrays
where bridge.n_rows <> arrays.n_tags
