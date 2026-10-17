-- Every period with a brand has a row in dim_brand, and brand_key is NULL exactly when there is no brand.
select h.history_key
from {{ ref('product_history') }} as h
left join {{ ref('dim_brand') }} as b on h.brand_key = b.brand_key
where (h.first_brand is not null and b.brand_key is null)
   or (h.first_brand is null and h.brand_key is not null)
