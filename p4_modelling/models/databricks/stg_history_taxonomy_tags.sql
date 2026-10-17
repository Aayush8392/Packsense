{{ config(materialized='view') }}

-- One row per history period, tag and kind, for the two taxonomy-backed tag lists beyond allergens: categories_tags and labels_tags.
-- Databricks-only: the array explode is engine-specific; the two bridges and the dimensions built on it are portable. array_distinct guards
-- against a tag listed twice in one period; a NULL array gives no rows.
select h.history_key, h.code, h.valid_from_t, 'category' as kind, c.tag
from {{ ref('product_history') }} as h
lateral view explode(array_distinct(h.categories_tags)) c as tag
union all
select h.history_key, h.code, h.valid_from_t, 'label' as kind, l.tag
from {{ ref('product_history') }} as h
lateral view explode(array_distinct(h.labels_tags)) l as tag
