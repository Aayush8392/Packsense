{{ config(materialized='view') }}

-- DuckDB twin of the Databricks view of the same name: `unnest` and `list_distinct` play the role of `explode` and `array_distinct`;
-- a NULL array gives no rows on both engines.
select h.history_key, h.code, h.valid_from_t, 'contains' as relationship, unnest(list_distinct(h.allergens_tags)) as allergen_tag
from {{ ref('product_history') }} as h
union all
select h.history_key, h.code, h.valid_from_t, 'may_contain' as relationship, unnest(list_distinct(h.traces_tags)) as allergen_tag
from {{ ref('product_history') }} as h
