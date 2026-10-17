{{ config(materialized='view') }}

-- DuckDB twin of the Databricks view of the same name: one row per history period per country tag.
select
    h.history_key,
    h.code,
    h.valid_from_t,
    unnest(list_distinct(h.countries_tags)) as market_code
from {{ ref('product_history') }} as h
