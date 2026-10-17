{#
  tag_dimension: one row per raw tag seen in a bridge, resolved against the newest snapshot of one taxonomy, the way dim_allergen does it:
    match_type 'tag'       : the tag IS a canonical tag of the taxonomy,
    match_type 'name'      : the text after the language prefix equals, ignoring case, exactly one tag's name in some language,
    match_type 'ambiguous' : that text is the name of several tags: no canonical tag is chosen, nothing is guessed,
    match_type 'none'      : the taxonomy does not know it (the tag keeps itself as its name).
  canonical_tag / canonical_name are set exactly for 'tag' and 'name'. The hierarchy comes from the taxonomy: parents (the canonical tag's
  direct parents), n_children, is_root. n_products counts distinct products that ever carried the raw tag.
  The match is deterministic (case-insensitive equality of a written name through name_key), never fuzzy.
#}
{% macro tag_dimension(bridge, tag_column, taxonomy, prefix) %}
with raw as (
    select
        {{ tag_column }} as raw_tag,
        {{ name_key("regexp_replace(" ~ tag_column ~ ", '^[^:]*:', '')") }} as text_key,
        count(distinct code) as n_products
    from {{ ref(bridge) }}
    group by {{ tag_column }}
),

resolved as (
    select
        r.raw_tag,
        r.n_products,
        t.tag as exact_tag,
        n.n_tags,
        n.tag as name_tag
    from raw as r
    left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = '{{ taxonomy }}' and t.tag = r.raw_tag
    left join {{ ref('taxonomy_name_lookup') }} as n on n.taxonomy = '{{ taxonomy }}' and n.name_key = r.text_key
)

select
    x.raw_tag as {{ prefix }}_tag,
    coalesce(c.name_en, x.raw_tag) as {{ prefix }}_name,
    case when x.exact_tag is null then 0 else 1 end as taxonomy_matched,
    case
        when x.exact_tag is not null then 'tag'
        when x.name_tag is not null and x.n_tags = 1 then 'name'
        when x.name_tag is not null then 'ambiguous'
        else 'none'
    end as match_type,
    case
        when x.exact_tag is not null then x.exact_tag
        when x.name_tag is not null and x.n_tags = 1 then x.name_tag
    end as canonical_tag,
    c.name_en as canonical_name,
    c.parents as parents,
    case when c.tag is null then null else {{ distinct_array_size('c.children') }} end as n_children,
    case when c.tag is null then null when {{ distinct_array_size('c.parents') }} = 0 then 1 else 0 end as is_root,
    x.n_products
from resolved as x
left join {{ ref('taxonomy_tag_latest') }} as c
    on c.taxonomy = '{{ taxonomy }}'
    and c.tag = case when x.exact_tag is not null then x.exact_tag when x.n_tags = 1 then x.name_tag end
{% endmacro %}
