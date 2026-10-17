-- For one product and flag, a later span starts only after the earlier one has vanished (and an open span has no successor).
select code, severity, flag, first_seen_t
from (
    select
        code, severity, flag, first_seen_t,
        lag(vanished_at_t) over (partition by code, severity, flag order by first_seen_t) as prev_vanished_at_t,
        lag(is_open) over (partition by code, severity, flag order by first_seen_t) as prev_is_open
    from {{ ref('product_flag_spans') }}
) as s
where prev_is_open = 1 or (prev_vanished_at_t is not null and first_seen_t <= prev_vanished_at_t)
