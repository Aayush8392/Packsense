-- The replay must agree with the daily quality fact on EVERY complete day, not only the last one (quality_open_spans_equal_open_flag_spans
-- checks the last day). Scope `all`: the open flag spans per severity and the products held at the end of each day, counted by the replay
-- predicates, must equal the fact's running sums. A day on which the fact has a value and the replay has none (or the reverse) is a difference.
with days as (
    select distinct snapshot_date as d from {{ ref('fct_catalogue_quality_daily') }}
),

replay_spans as (
    select dd.d, s.severity, count(*) as n
    from days as dd
    inner join {{ ref('product_flag_spans') }} as s on {{ spans_as_of('dd.d', 's') }}
    group by dd.d, s.severity
),

fact_spans as (
    select snapshot_date as d, severity, sum(open_spans) as n
    from {{ ref('fct_catalogue_quality_daily') }}
    where scope = 'all'
    group by snapshot_date, severity
),

first_day_seen as (
    select code, min({{ epoch_date('valid_from_t') }}) as first_d from {{ ref('product_history') }} group by code
),

replay_held as (
    select dd.d, count(*) as n
    from days as dd
    inner join first_day_seen as f on f.first_d <= dd.d
    group by dd.d
),

fact_held as (
    select snapshot_date as d, max(n_products_held) as n
    from {{ ref('fct_catalogue_quality_daily') }}
    where scope = 'all'
    group by snapshot_date
)

select coalesce(r.d, f.d) as d, coalesce(r.severity, f.severity) as severity, coalesce(r.n, 0) as replay, coalesce(f.n, 0) as fact, 'open spans' as what
from replay_spans as r
full outer join fact_spans as f on r.d = f.d and r.severity = f.severity
where coalesce(r.n, 0) <> coalesce(f.n, 0)

union all

select coalesce(r.d, f.d) as d, 'all' as severity, coalesce(r.n, 0) as replay, coalesce(f.n, 0) as fact, 'products held' as what
from replay_held as r
full outer join fact_held as f on r.d = f.d
where coalesce(r.n, 0) <> coalesce(f.n, 0)
