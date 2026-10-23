-- The card's OFF flag counts equal the open flag spans counted straight from product_flag_spans (error, bug, warning, info), product by product, and the card
-- holds exactly the products of the history (one each).
with spans as (
    select code,
           sum(case when severity = 'error' then 1 else 0 end) as e,
           sum(case when severity = 'bug' then 1 else 0 end) as b,
           sum(case when severity = 'warning' then 1 else 0 end) as w,
           sum(case when severity = 'info' then 1 else 0 end) as i
    from {{ ref('product_flag_spans') }}
    where is_open = 1
    group by code
),
history as (
    select distinct code from {{ ref('product_history') }}
)
select coalesce(c.code, h.code) as code
from {{ ref('mart_product_card') }} as c
full outer join history as h on h.code = c.code
left join spans as s on s.code = h.code
where c.code is null or h.code is null
   or c.off_error <> coalesce(s.e, 0) or c.off_bug <> coalesce(s.b, 0) or c.off_warning <> coalesce(s.w, 0) or c.off_info <> coalesce(s.i, 0)
