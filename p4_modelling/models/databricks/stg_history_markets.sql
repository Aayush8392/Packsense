{{ config(materialized='view') }}

-- One row per history period per country tag. Databricks-only: the array explode is engine-specific; the bridge and the market
-- dimension built on it are portable.
select
    h.history_key,
    h.code,
    h.valid_from_t,
    m.market_code
from {{ ref('product_history') }} as h
lateral view explode(array_distinct(h.countries_tags)) m as market_code
