{{ config(materialized='table') }}

-- One row per allergen tag seen in the history (the raw, user-entered tag), resolved against OFF's allergens taxonomy (newest snapshot):
--   match_type 'tag'       : the tag IS a canonical taxonomy tag (en:milk),
--   match_type 'name'      : the text after the language prefix equals, ignoring case, exactly one taxonomy tag's name in some language
--                            (en:Milch, fr:lait, fr:Avoine: real allergens entered under the wrong language prefix or in the wrong case),
--   match_type 'ambiguous' : that text is the name of more than one tag: no canonical tag is chosen, nothing is guessed,
--   match_type 'none'      : the taxonomy does not know it (it keeps the raw tag as its name).
-- canonical_tag / canonical_name are set exactly for 'tag' and 'name'. taxonomy_matched = 1 only for the exact canonical tag (as before).
-- The match is deterministic (case-insensitive equality of a written name), never fuzzy. products_* count distinct products that ever carried the tag.
with raw as (
    select
        allergen_tag,
        {{ name_key("regexp_replace(allergen_tag, '^[^:]*:', '')") }} as text_key,
        count(distinct case when relationship = 'contains' then code end) as products_contains,
        count(distinct case when relationship = 'may_contain' then code end) as products_may_contain
    from {{ ref('bridge_product_allergen') }}
    group by allergen_tag
),

resolved as (
    select
        r.allergen_tag,
        r.products_contains,
        r.products_may_contain,
        t.tag as exact_tag,
        n.n_tags,
        n.tag as name_tag
    from raw as r
    left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'allergens' and t.tag = r.allergen_tag
    left join {{ ref('taxonomy_name_lookup') }} as n on n.taxonomy = 'allergens' and n.name_key = r.text_key
)

select
    x.allergen_tag,
    coalesce(c.name_en, x.allergen_tag) as allergen_name,
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
    x.products_contains,
    x.products_may_contain
from resolved as x
left join {{ ref('taxonomy_tag_latest') }} as c
    on c.taxonomy = 'allergens'
    and c.tag = case when x.exact_tag is not null then x.exact_tag when x.n_tags = 1 then x.name_tag end
