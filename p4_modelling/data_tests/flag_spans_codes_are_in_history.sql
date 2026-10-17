-- Every flagged product exists in the history table.
select distinct f.code
from {{ ref('product_flag_spans') }} as f
left join (select distinct code from {{ ref('product_history') }}) as h on f.code = h.code
where h.code is null
