-- The match columns of dim_allergen agree: a canonical tag exists exactly for match_type 'tag' or 'name', an exact match is its own canonical
-- tag, and the canonical tag is a real tag of the allergens taxonomy (so a name match can never invent one).
select d.allergen_tag, d.match_type, d.canonical_tag
from {{ ref('dim_allergen') }} as d
left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'allergens' and t.tag = d.canonical_tag
where (d.match_type in ('tag', 'name') and (d.canonical_tag is null or t.tag is null))
   or (d.match_type in ('ambiguous', 'none') and d.canonical_tag is not null)
   or (d.match_type = 'tag' and (d.canonical_tag <> d.allergen_tag or d.taxonomy_matched <> 1))
   or (d.match_type <> 'tag' and d.taxonomy_matched <> 0)
