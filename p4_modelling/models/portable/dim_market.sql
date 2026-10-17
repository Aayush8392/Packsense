{{ config(materialized='table') }}

-- One row per country tag seen in the history. Coverage differs by market: India has the one-time seed plus every daily delta; every
-- other market arrives only through the daily deltas, i.e. products edited since the capture began. Nothing published may make a
-- global-catalogue claim from the non-India rows. Readable names and ISO codes come from OFF's countries taxonomy (newest snapshot);
-- a tag the taxonomy does not know keeps the tag as its name and taxonomy_matched = 0.
select
    m.market_code,
    case when m.market_code = 'en:india' then 1 else 0 end as is_target_market,
    case
        when m.market_code = 'en:india' then 'seed plus daily deltas'
        else 'daily deltas only (products edited since the capture began)'
    end as coverage,
    coalesce(c.name_en, m.market_code) as market_name,
    {{ map_get('c.props', 'country_code_2') }} as country_code_2,
    {{ map_get('c.props', 'country_code_3') }} as country_code_3,
    case when c.tag is null then 0 else 1 end as taxonomy_matched
from (select distinct market_code from {{ ref('bridge_product_market') }}) as m
left join {{ ref('taxonomy_tag_latest') }} as c on c.taxonomy = 'countries' and c.tag = m.market_code
