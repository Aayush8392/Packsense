{{ config(materialized='table', post_hook="{{ apply_market_filter(this) }}") }}

-- One row per country tag seen in the history (the raw, user-entered tag). Coverage differs by market: India has the one-time seed plus every
-- daily delta; every other market arrives only through the daily deltas, i.e. products edited since the capture began. Nothing published may
-- make a global-catalogue claim from the non-India rows. The tag is resolved against OFF's countries taxonomy (newest snapshot) exactly as
-- allergens are (see dim_allergen): match_type 'tag' (canonical), 'name' (the text after the prefix equals one country's name in some
-- language, ignoring case: en:Türkiye), 'ambiguous' (a name shared by several countries: nothing chosen) or 'none'.
-- market_name, country_code_2 and country_code_3 come from the canonical country; an unresolved tag keeps itself as its name.
-- is_target_market is decided on the canonical tag, so a variant spelling of India counts as India.
with raw as (
    select
        market_code,
        {{ name_key("regexp_replace(market_code, '^[^:]*:', '')") }} as text_key
    from (select distinct market_code from {{ ref('bridge_product_market') }}) as m
),

resolved as (
    select
        r.market_code,
        t.tag as exact_tag,
        n.n_tags,
        n.tag as name_tag
    from raw as r
    left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'countries' and t.tag = r.market_code
    left join {{ ref('taxonomy_name_lookup') }} as n on n.taxonomy = 'countries' and n.name_key = r.text_key
),

canonical as (
    select
        market_code,
        exact_tag,
        case
            when exact_tag is not null then 'tag'
            when name_tag is not null and n_tags = 1 then 'name'
            when name_tag is not null then 'ambiguous'
            else 'none'
        end as match_type,
        case
            when exact_tag is not null then exact_tag
            when name_tag is not null and n_tags = 1 then name_tag
        end as canonical_tag
    from resolved
)

select
    k.market_code,
    case when coalesce(k.canonical_tag, k.market_code) = 'en:india' then 1 else 0 end as is_target_market,
    case
        when coalesce(k.canonical_tag, k.market_code) = 'en:india' then 'seed plus daily deltas'
        else 'daily deltas only (products edited since the capture began)'
    end as coverage,
    coalesce(c.name_en, k.market_code) as market_name,
    {{ map_get('c.props', 'country_code_2') }} as country_code_2,
    {{ map_get('c.props', 'country_code_3') }} as country_code_3,
    case when k.exact_tag is null then 0 else 1 end as taxonomy_matched,
    k.match_type,
    k.canonical_tag
from canonical as k
left join {{ ref('taxonomy_tag_latest') }} as c on c.taxonomy = 'countries' and c.tag = k.canonical_tag
