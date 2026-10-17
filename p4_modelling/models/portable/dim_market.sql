{{ config(materialized='table') }}

-- One row per country tag seen in the history. Coverage differs by market: India has the one-time seed plus every daily delta; every
-- other market arrives only through the daily deltas, i.e. products edited since the capture began. Nothing published may make a
-- global-catalogue claim from the non-India rows. Readable country names wait for the taxonomy loader.
select
    market_code,
    case when market_code = 'en:india' then 1 else 0 end as is_target_market,
    case
        when market_code = 'en:india' then 'seed plus daily deltas'
        else 'daily deltas only (products edited since the capture began)'
    end as coverage
from (select distinct market_code from {{ ref('bridge_product_market') }}) as markets
