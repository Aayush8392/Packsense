-- One row per input set: no product has two sets with the same source, preparation, basis and quantity.
select code, source, preparation, per, per_quantity, count(*) as n
from {{ ref('product_nutrition_sets') }}
group by code, source, preparation, per, per_quantity
having count(*) > 1
