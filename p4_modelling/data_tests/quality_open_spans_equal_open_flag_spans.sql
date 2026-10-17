-- Independent check of the daily quality fact on its last day (the newest COMPLETE day): the open spans per scope and severity must equal the
-- spans open at the end of that day, counted straight from product_flag_spans (opened on or before the day and not vanished by it, with no
-- running sum); and the products held per scope must equal the distinct products first seen on or before the day.
with last_day as (
    select max(snapshot_date) as d from {{ ref('fct_catalogue_quality_daily') }}
),

india as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

open_at_end as (
    select s.code, s.severity
    from {{ ref('product_flag_spans') }} as s
    cross join last_day as l
    where {{ epoch_date('s.first_seen_t') }} <= l.d
      and (s.vanished_at_t is null or {{ epoch_date('s.vanished_at_t') }} > l.d)
),

expected_spans as (
    select 'all' as scope, severity, count(*) as n from open_at_end group by severity
    union all
    select 'india' as scope, o.severity, count(*) as n
    from open_at_end as o inner join india as i on i.code = o.code
    group by o.severity
),

got_spans as (
    select f.scope, f.severity, sum(f.open_spans) as n
    from {{ ref('fct_catalogue_quality_daily') }} as f inner join last_day as l on l.d = f.snapshot_date
    group by f.scope, f.severity
),

first_day_seen as (
    select code, min({{ epoch_date('valid_from_t') }}) as d from {{ ref('product_history') }} group by code
),

expected_held as (
    select 'all' as scope, count(*) as n from first_day_seen as f cross join last_day as l where f.d <= l.d
    union all
    select 'india' as scope, count(*) as n
    from first_day_seen as f cross join last_day as l inner join india as i on i.code = f.code
    where f.d <= l.d
),

got_held as (
    select f.scope, max(f.n_products_held) as n
    from {{ ref('fct_catalogue_quality_daily') }} as f inner join last_day as l on l.d = f.snapshot_date
    group by f.scope
)

select e.scope, e.severity, e.n as expected, coalesce(g.n, 0) as got, 'open spans' as what
from expected_spans as e
left join got_spans as g on g.scope = e.scope and g.severity = e.severity
where e.n <> coalesce(g.n, 0)

union all

select e.scope, 'all' as severity, e.n as expected, coalesce(g.n, 0) as got, 'products held' as what
from expected_held as e
left join got_held as g on g.scope = e.scope
where e.n <> coalesce(g.n, 0)
