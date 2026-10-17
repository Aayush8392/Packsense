-- A name carried by more than one taxonomy tag is ambiguous: neither dimension may resolve a tag through it.
select d.allergen_tag as tag, d.match_type
from {{ ref('dim_allergen') }} as d
where d.match_type = 'name'
  and exists (
      select 1 from {{ ref('taxonomy_name_lookup') }} as n
      where n.taxonomy = 'allergens' and n.name_key = lower(trim(regexp_replace(d.allergen_tag, '^[^:]*:', ''))) and n.n_tags <> 1
  )
union all
select m.market_code as tag, m.match_type
from {{ ref('dim_market') }} as m
where m.match_type = 'name'
  and exists (
      select 1 from {{ ref('taxonomy_name_lookup') }} as n
      where n.taxonomy = 'countries' and n.name_key = lower(trim(regexp_replace(m.market_code, '^[^:]*:', ''))) and n.n_tags <> 1
  )
