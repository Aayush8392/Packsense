{{ config(materialized='table') }}

-- Which labels (organic, vegan, fair trade, ...) a history period carries: one row per period and label tag (the raw, user-entered tag;
-- dim_label resolves it).
select history_key, code, valid_from_t, tag as label_tag
from {{ ref('stg_history_taxonomy_tags') }}
where kind = 'label'
