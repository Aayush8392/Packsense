{{ config(materialized='table') }}

-- One row per allergen tag seen in the history, with its English name from OFF's allergens taxonomy (newest snapshot). Allergen tags are
-- user-entered, so some are not in the taxonomy (non-canonical spellings, other languages): they keep the tag as their name and
-- taxonomy_matched = 0, so nobody mistakes them for a recognised allergen. products_* count distinct products that ever carried the tag.
select
    b.allergen_tag,
    coalesce(t.name_en, b.allergen_tag) as allergen_name,
    case when t.tag is null then 0 else 1 end as taxonomy_matched,
    b.products_contains,
    b.products_may_contain
from (
    select
        allergen_tag,
        count(distinct case when relationship = 'contains' then code end) as products_contains,
        count(distinct case when relationship = 'may_contain' then code end) as products_may_contain
    from {{ ref('bridge_product_allergen') }}
    group by allergen_tag
) as b
left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'allergens' and t.tag = b.allergen_tag
