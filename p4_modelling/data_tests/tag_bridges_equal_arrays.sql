-- Each tag bridge holds one row per distinct tag of its array, for every period: nothing lost, nothing doubled.
select 'category' as kind, bridge.n_rows, arrays.n_tags
from (select count(*) as n_rows from {{ ref('bridge_product_category') }}) as bridge
cross join (select sum({{ distinct_array_size('categories_tags') }}) as n_tags from {{ ref('product_history') }}) as arrays
where bridge.n_rows <> arrays.n_tags
union all
select 'label' as kind, bridge.n_rows, arrays.n_tags
from (select count(*) as n_rows from {{ ref('bridge_product_label') }}) as bridge
cross join (select sum({{ distinct_array_size('labels_tags') }}) as n_tags from {{ ref('product_history') }}) as arrays
where bridge.n_rows <> arrays.n_tags
