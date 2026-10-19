{{ config(materialized='table', post_hook="{{ apply_market_filter(this) }}") }}

-- Which markets a history period was sold in: one row per period and country tag (a product can carry several countries).
select history_key, code, valid_from_t, market_code
from {{ ref('stg_history_markets') }}
