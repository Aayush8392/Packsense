-- Every allergen tag used by the bridge has a row in dim_allergen, and nothing else is in it.
select b.allergen_tag
from (select distinct allergen_tag from {{ ref('bridge_product_allergen') }}) as b
left join {{ ref('dim_allergen') }} as d on b.allergen_tag = d.allergen_tag
where d.allergen_tag is null
union all
select d.allergen_tag
from {{ ref('dim_allergen') }} as d
left join (select distinct allergen_tag from {{ ref('bridge_product_allergen') }}) as b on b.allergen_tag = d.allergen_tag
where b.allergen_tag is null
