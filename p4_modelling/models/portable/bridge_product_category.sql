{{ config(materialized='table') }}

-- Which categories a history period carries: one row per period and category tag (the raw, user-entered tag; dim_category resolves it).
-- OFF's categories_tags already lists the ancestors of each category, so the bridge needs no closure table (a data test checks it).
select history_key, code, valid_from_t, tag as category_tag
from {{ ref('stg_history_taxonomy_tags') }}
where kind = 'category'
