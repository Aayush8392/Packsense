-- The replay is only worth using if it reproduces what we held. For the first, a middle and the last complete day, the products and open flags
-- rebuilt from product_history and product_flag_spans (macros history_as_of / spans_as_of) must equal what silver says directly: the newest
-- version of each product dated on or before the day, compared by its tracked hash, and that version's own flag occurrences.
-- Two independent routes to the same state; a difference in either direction is a defect in the history, the spans or the predicates.
with cd as (
    select first_day, last_day from {{ complete_days() }} as c
),

days as (
    select first_day as d from cd
    union
    select last_day as d from cd
    union
    select calendar_date as d from (
        select
            t.calendar_date,
            row_number() over (order by t.calendar_date) as rn,
            count(*) over () as n
        from {{ ref('dim_date') }} as t
        inner join cd on t.calendar_date between cd.first_day and cd.last_day
    ) as m
    where rn = cast(floor((n + 1) / 2.0) as integer)
),

replayed as (
    select dd.d, h.code, h.tracked_hash
    from days as dd
    inner join {{ ref('product_history') }} as h on {{ history_as_of('dd.d', 'h') }}
),

direct as (
    select d, code, tracked_hash, last_modified_t
    from (
        select
            dd.d, v.code, v.tracked_hash, v.last_modified_t,
            row_number() over (partition by dd.d, v.code order by v.last_modified_t desc) as rn
        from days as dd
        inner join {{ ref('stg_silver_versions') }} as v on {{ epoch_date('v.last_modified_t') }} <= dd.d
    ) as x
    where rn = 1
),

replayed_flags as (
    select dd.d, s.code, s.severity, s.flag
    from days as dd
    inner join {{ ref('product_flag_spans') }} as s on {{ spans_as_of('dd.d', 's') }}
),

direct_flags as (
    select dd.d, o.code, o.severity, o.flag
    from direct as dd
    inner join {{ ref('stg_flag_occurrences') }} as o
        on o.code = dd.code
        and o.last_modified_t = dd.last_modified_t
),

state_diff as (
    select d, code, 'state only in replay' as what from (select d, code, tracked_hash from replayed except select d, code, tracked_hash from direct) as a
    union all
    select d, code, 'state only in silver' as what from (select d, code, tracked_hash from direct except select d, code, tracked_hash from replayed) as b
),

flag_diff as (
    select d, code, 'flag only in replay' as what from (select d, code, severity, flag from replayed_flags except select d, code, severity, flag from direct_flags) as a
    union all
    select d, code, 'flag only in silver' as what from (select d, code, severity, flag from direct_flags except select d, code, severity, flag from replayed_flags) as b
)

select * from state_diff
union all
select * from flag_diff
