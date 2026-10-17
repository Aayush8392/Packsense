-- The match columns of dim_market agree (same rules as dim_allergen, against the countries taxonomy).
select m.market_code, m.match_type, m.canonical_tag
from {{ ref('dim_market') }} as m
left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'countries' and t.tag = m.canonical_tag
where (m.match_type in ('tag', 'name') and (m.canonical_tag is null or t.tag is null))
   or (m.match_type in ('ambiguous', 'none') and m.canonical_tag is not null)
   or (m.match_type = 'tag' and (m.canonical_tag <> m.market_code or m.taxonomy_matched <> 1))
   or (m.match_type <> 'tag' and m.taxonomy_matched <> 0)
