-- The complete-day bounds (macro complete_days) agree with a second formulation of the same rule, and the quality fact spans exactly those days.
-- A day is complete when all of its 24 hours lie inside the covered window [earliest window start, latest window end]:
--   first complete day = the day of (earliest start + 86399 s)   (the first midnight at or after the start)
--   last complete day  = the day of (latest end - 86400 s)       (the day before the last midnight at or before the end)
-- An earlier version of the macro dropped a pair of brackets and ran to 2035 while every other test passed: this test is what catches that.
with window_bounds as (
    select
        {{ epoch_date('min(delta_start_t) + 86399') }} as first_day,
        {{ epoch_date('max(delta_end_t) - 86400') }} as last_day
    from {{ ref('stg_silver_versions') }}
    where not is_seed
),

macro_bounds as (
    select first_day, last_day from {{ complete_days() }} as cd
),

quality_days as (
    select min(snapshot_date) as first_day, max(snapshot_date) as last_day from {{ ref('fct_catalogue_quality_daily') }}
)

select 'macro differs from the window arithmetic' as problem, m.first_day, m.last_day
from macro_bounds as m cross join window_bounds as w
where m.first_day <> w.first_day or m.last_day <> w.last_day

union all

select 'quality fact does not span the complete days' as problem, q.first_day, q.last_day
from quality_days as q cross join macro_bounds as m
where q.first_day <> m.first_day or q.last_day <> m.last_day
