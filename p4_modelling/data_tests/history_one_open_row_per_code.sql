-- Exactly one open period per code; valid_to_t is NULL only on that row.
select code, sum(case when valid_to_t is null then 1 else 0 end) as open_rows
from {{ ref('product_history') }}
group by code
having sum(case when valid_to_t is null then 1 else 0 end) <> 1
