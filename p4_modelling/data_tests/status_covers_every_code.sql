-- Every product in the history has a status row (and so can never be read as "exists" by default).
select h.code
from (select distinct code from {{ ref('product_history') }}) as h
left join {{ ref('product_status') }} as s on h.code = s.code
where s.code is null
