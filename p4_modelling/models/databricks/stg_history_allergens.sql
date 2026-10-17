{{ config(materialized='view') }}

-- One row per history period, allergen tag and relationship. Databricks-only: the array explode is engine-specific; the bridge, the
-- dimension and the change log built on it are portable. `contains` comes from allergens_tags (what the pack declares), `may_contain`
-- from traces_tags (precautionary "may contain"). array_distinct guards against a tag listed twice in one period.
select h.history_key, h.code, h.valid_from_t, 'contains' as relationship, a.allergen_tag
from {{ ref('product_history') }} as h
lateral view explode(array_distinct(h.allergens_tags)) a as allergen_tag
union all
select h.history_key, h.code, h.valid_from_t, 'may_contain' as relationship, t.allergen_tag
from {{ ref('product_history') }} as h
lateral view explode(array_distinct(h.traces_tags)) t as allergen_tag
