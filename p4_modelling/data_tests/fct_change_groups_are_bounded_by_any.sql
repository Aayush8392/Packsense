-- Group rows overlap, so they are bounded, not summed: for every (day, scope, seed flag) no single group has more periods than the 'any' row,
-- the groups together have at least as many as 'any' (every period is in at least one group, or is a new product), and the India scope never
-- exceeds the all-markets scope for the same row.
select g.change_date, g.scope, g.change_group, g.opened_by_seed, 'group above any' as problem
from {{ ref('fct_product_change_daily') }} as g
left join {{ ref('fct_product_change_daily') }} as a
    on a.change_date = g.change_date and a.scope = g.scope and a.opened_by_seed = g.opened_by_seed and a.change_group = 'any'
where g.change_group <> 'any' and (a.n_periods is null or g.n_periods > a.n_periods)

union all

select a.change_date, a.scope, 'any' as change_group, a.opened_by_seed, 'groups do not cover any' as problem
from {{ ref('fct_product_change_daily') }} as a
inner join (
    select change_date, scope, opened_by_seed, sum(n_periods) as total
    from {{ ref('fct_product_change_daily') }}
    where change_group <> 'any'
    group by change_date, scope, opened_by_seed
) as s on s.change_date = a.change_date and s.scope = a.scope and s.opened_by_seed = a.opened_by_seed
where a.change_group = 'any' and s.total < a.n_periods

union all

select i.change_date, i.scope, i.change_group, i.opened_by_seed, 'india above all' as problem
from {{ ref('fct_product_change_daily') }} as i
left join {{ ref('fct_product_change_daily') }} as a
    on a.change_date = i.change_date and a.scope = 'all' and a.change_group = i.change_group and a.opened_by_seed = i.opened_by_seed
where i.scope = 'india' and (a.n_periods is null or i.n_periods > a.n_periods)
