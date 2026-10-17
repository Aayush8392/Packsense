{{ config(materialized='table') }}

-- Which allergens a history period declares: one row per period, allergen tag and relationship. One bridge with a relationship column
-- (contains | may_contain) because OFF gives both as the same kind of tag list.
select history_key, code, valid_from_t, relationship, allergen_tag
from {{ ref('stg_history_allergens') }}
