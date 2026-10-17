-- The allergen bridge holds one row per distinct tag of allergens_tags (contains) and of traces_tags (may_contain) of every period: nothing lost, nothing doubled.
select bridge.n_rows, arrays.n_tags
from (select count(*) as n_rows from {{ ref('bridge_product_allergen') }}) as bridge
cross join (
    select sum({{ distinct_array_size('allergens_tags') }} + {{ distinct_array_size('traces_tags') }}) as n_tags
    from {{ ref('product_history') }}
) as arrays
where bridge.n_rows <> arrays.n_tags
