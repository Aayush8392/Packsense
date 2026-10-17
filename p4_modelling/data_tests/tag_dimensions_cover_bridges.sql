-- Every category and label tag used by a bridge has exactly one row in its dimension, and the dimension holds nothing else.
select 'category' as kind, b.category_tag as tag
from (select distinct category_tag from {{ ref('bridge_product_category') }}) as b
left join {{ ref('dim_category') }} as d on b.category_tag = d.category_tag
where d.category_tag is null
union all
select 'category', d.category_tag
from {{ ref('dim_category') }} as d
left join (select distinct category_tag from {{ ref('bridge_product_category') }}) as b on b.category_tag = d.category_tag
where b.category_tag is null
union all
select 'label', b.label_tag
from (select distinct label_tag from {{ ref('bridge_product_label') }}) as b
left join {{ ref('dim_label') }} as d on b.label_tag = d.label_tag
where d.label_tag is null
union all
select 'label', d.label_tag
from {{ ref('dim_label') }} as d
left join (select distinct label_tag from {{ ref('bridge_product_label') }}) as b on b.label_tag = d.label_tag
where b.label_tag is null
