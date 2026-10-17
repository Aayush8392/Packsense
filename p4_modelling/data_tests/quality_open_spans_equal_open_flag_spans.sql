-- Independent check of the daily quality fact on its last day: the open spans per scope and severity must equal the spans that product_flag_spans
-- marks open (is_open = 1), counted without the fact's date arithmetic; and the products held per scope must equal the distinct products in the history.
with last_day as (
    select max(snapshot_date) as d from {{ ref('fct_catalogue_quality_daily') }}
),

india as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

expected_spans as (
    select 'all' as scope, severity, count(*) as n from {{ ref('product_flag_spans') }} where is_open = 1 group by severity
    union all
    select 'india' as scope, s.severity, count(*) as n
    from {{ ref('product_flag_spans') }} as s inner join india as i on i.code = s.code
    where s.is_open = 1 group by s.severity
),

got_spans as (
    select f.scope, f.severity, sum(f.open_spans) as n
    from {{ ref('fct_catalogue_quality_daily') }} as f inner join last_day as l on l.d = f.snapshot_date
    group by f.scope, f.severity
),

expected_held as (
    select 'all' as scope, count(distinct code) as n from {{ ref('product_history') }}
    union all
    select 'india' as scope, count(distinct h.code) as n from {{ ref('product_history') }} as h inner join india as i on i.code = h.code
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
