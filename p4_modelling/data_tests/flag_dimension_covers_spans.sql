-- Every flag in the spans has a row in dim_flag, and nothing else is in it.
select s.flag
from (select distinct flag from {{ ref('product_flag_spans') }}) as s
left join {{ ref('dim_flag') }} as d on s.flag = d.flag
where d.flag is null
union all
select d.flag
from {{ ref('dim_flag') }} as d
left join (select distinct flag from {{ ref('product_flag_spans') }}) as s on s.flag = d.flag
where s.flag is null
