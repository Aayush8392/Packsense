-- Independent check of the India release mart: the products it holds must be exactly the products whose newest period (found by row_number over
-- valid_from_t, not by the is_latest_observed flag the model uses) lists the India market and whose existence status is not 'confirmed_not_found' or
-- 'moved_other_type' (a left join to the status table, not the inner join the model uses). Any difference in either direction is a failure.
with newest as (
    select h.history_key, h.code,
           row_number() over (partition by h.code order by h.valid_from_t desc) as rn
    from {{ ref('product_history') }} as h
),

india as (
    select distinct n.code
    from newest as n
    inner join {{ ref('bridge_product_market') }} as b on b.history_key = n.history_key
    inner join {{ ref('dim_market') }} as m on m.market_code = b.market_code
    where n.rn = 1 and m.is_target_market = 1
),

expected as (
    select i.code
    from india as i
    left join {{ ref('product_status') }} as s on s.code = i.code
    where coalesce(s.status, 'unverified') not in ('confirmed_not_found', 'moved_other_type')
)

select e.code, 'missing from the mart' as problem
from expected as e
left join {{ ref('mart_india_release') }} as r on r.code = e.code
where r.code is null

union all

select r.code, 'in the mart but not expected' as problem
from {{ ref('mart_india_release') }} as r
left join expected as e on e.code = r.code
where e.code is null
