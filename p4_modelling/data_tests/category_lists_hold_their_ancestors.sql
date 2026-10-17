{{ config(severity='warn') }}
-- OFF's categories_tags lists the ancestors of each category, which is why the category bridge needs no closure table. This checks it on the
-- data: for every period and every exact (canonical) category tag, all its direct parents in the newest taxonomy are in the same period's
-- list. A WARN, not a failure: a taxonomy can change under an old period, and the count tells how far the claim holds.
select b.history_key, b.category_tag
from {{ ref('bridge_product_category') }} as b
inner join {{ ref('dim_category') }} as d on d.category_tag = b.category_tag and d.match_type = 'tag'
inner join {{ ref('product_history') }} as h on h.history_key = b.history_key
where {{ array_missing_count('d.parents', 'h.categories_tags') }} > 0
