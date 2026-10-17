-- The bridge holds one row per distinct country tag of every period, nothing lost or doubled (array size through a per-engine macro).
select bridge.n_rows, arrays.n_tags
from (select count(*) as n_rows from {{ ref('bridge_product_market') }}) as bridge
cross join (
    select sum({{ distinct_array_size('countries_tags') }}) as n_tags
    from {{ ref('product_history') }}
) as arrays
where bridge.n_rows <> arrays.n_tags
