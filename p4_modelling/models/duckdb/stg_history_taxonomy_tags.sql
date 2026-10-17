{{ config(materialized='view') }}

-- DuckDB twin of the Databricks view of the same name: `unnest` and `list_distinct` play the role of `explode` and `array_distinct`;
-- a NULL array gives no rows on both engines.
select h.history_key, h.code, h.valid_from_t, 'category' as kind, unnest(list_distinct(h.categories_tags)) as tag
from {{ ref('product_history') }} as h
union all
select h.history_key, h.code, h.valid_from_t, 'label' as kind, unnest(list_distinct(h.labels_tags)) as tag
from {{ ref('product_history') }} as h
