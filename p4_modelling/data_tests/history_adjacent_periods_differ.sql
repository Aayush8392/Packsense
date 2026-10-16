-- Every new period is a real change: two neighbouring periods of one code never carry the same tracked set.
select code, valid_from_t
from (
    select code, valid_from_t, tracked_hash,
           lag(tracked_hash) over (partition by code order by valid_from_t) as prev_hash
    from {{ ref('product_history') }}
) as p
where prev_hash is not null and prev_hash = tracked_hash
