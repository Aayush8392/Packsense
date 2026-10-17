-- Independent check of the change log: across all pairs of consecutive periods, (tags added) - (tags removed) must equal the growth of the
-- allergen tag counts from the earlier period to the later one, computed straight from the arrays (not through the bridge).
with pairs as (
    select p.history_key as prev_key, c.history_key as curr_key
    from {{ ref('product_history') }} as p
    inner join {{ ref('product_history') }} as c on p.code = c.code and p.valid_to_t = c.valid_from_t
),

sizes as (
    select history_key, {{ distinct_array_size('allergens_tags') }} + {{ distinct_array_size('traces_tags') }} as n
    from {{ ref('product_history') }}
)

select expected.diff as expected_net_change, got.diff as logged_net_change
from (
    select coalesce(sum(sc.n - sp.n), 0) as diff
    from pairs as pr
    inner join sizes as sp on sp.history_key = pr.prev_key
    inner join sizes as sc on sc.history_key = pr.curr_key
) as expected
cross join (
    select coalesce(sum(case when change_type = 'added' then 1 else -1 end), 0) as diff
    from {{ ref('mart_allergen_change_log') }}
) as got
where expected.diff <> got.diff
