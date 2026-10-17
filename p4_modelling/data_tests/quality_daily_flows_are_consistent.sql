-- The running sum is honest: from one day to the next, open_spans changes by exactly opened + carried in - vanished; it is never negative; a
-- span that vanished with a tracked change is a vanished span; and the products held never fall from one day to the next.
select snapshot_date, scope, severity, flag_family, 'open spans do not follow the flows' as problem
from (
    select
        *,
        lag(open_spans) over (partition by scope, severity, flag_family order by snapshot_date) as prev_open
    from {{ ref('fct_catalogue_quality_daily') }}
) as x
where open_spans < 0 or (prev_open is not null and open_spans <> prev_open + opened_on_known_product + carried_in - vanished)

union all

select snapshot_date, scope, severity, flag_family, 'tracked-change vanishes exceed vanishes' as problem
from {{ ref('fct_catalogue_quality_daily') }}
where vanished_with_tracked_change > vanished

union all

select snapshot_date, scope, 'all' as severity, 'all' as flag_family, 'products held fell' as problem
from (
    select
        snapshot_date, scope, n_products_held,
        lag(n_products_held) over (partition by scope order by snapshot_date) as prev_held
    from (select distinct snapshot_date, scope, n_products_held from {{ ref('fct_catalogue_quality_daily') }}) as d
) as y
where prev_held is not null and n_products_held < prev_held
