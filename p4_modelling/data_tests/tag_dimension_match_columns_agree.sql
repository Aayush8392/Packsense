-- The match columns of dim_category and dim_label agree (as for dim_allergen): a canonical tag exists exactly for match_type 'tag' or 'name',
-- an exact match is its own canonical tag, the canonical tag is a real tag of that taxonomy, and the hierarchy columns are set exactly then.
select 'category' as kind, d.category_tag as tag, d.match_type, d.canonical_tag
from {{ ref('dim_category') }} as d
left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'categories' and t.tag = d.canonical_tag
where (d.match_type in ('tag', 'name') and (d.canonical_tag is null or t.tag is null or d.is_root is null or d.n_children is null))
   or (d.match_type in ('ambiguous', 'none') and (d.canonical_tag is not null or d.is_root is not null or d.n_children is not null))
   or (d.match_type = 'tag' and (d.canonical_tag <> d.category_tag or d.taxonomy_matched <> 1))
   or (d.match_type <> 'tag' and d.taxonomy_matched <> 0)
union all
select 'label', d.label_tag, d.match_type, d.canonical_tag
from {{ ref('dim_label') }} as d
left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'labels' and t.tag = d.canonical_tag
where (d.match_type in ('tag', 'name') and (d.canonical_tag is null or t.tag is null or d.is_root is null or d.n_children is null))
   or (d.match_type in ('ambiguous', 'none') and (d.canonical_tag is not null or d.is_root is not null or d.n_children is not null))
   or (d.match_type = 'tag' and (d.canonical_tag <> d.label_tag or d.taxonomy_matched <> 1))
   or (d.match_type <> 'tag' and d.taxonomy_matched <> 0)
