{{ config(severity='warn', enabled=(target.type == 'databricks' and not var('fixture_mode', false))) }}
-- A missing delta file must not look like a complete day (review 02, adoption A5). macro complete_days() takes the first and last day our files
-- cover from the earliest window start and the latest window end; if a file in between is missing from silver, the days it should have
-- covered would still be counted as complete and both daily facts would show a hole as a quiet day. OFF's delta windows are exactly
-- contiguous (each starts where the previous one ended: 17 windows checked on production 2026-10-18, 0 gaps), so any row here is either a
-- missing or unloaded file (a gap) or an overlap.
-- A WARN, not an error: a file OFF no longer lists (older than its 14-day window) cannot be recovered, and a permanent gap must not turn the
-- gold job red for ever; it shows in the run text after 'warned:' for as long as the gap exists. It compares the windows silver holds with each
-- other and reads no clock, but the fixture is a chosen slice of products (its windows are not a complete series), so it is disabled on DuckDB
-- and in fixture mode like the freshness check.
with windows as (
    select distinct delta_start_t, delta_end_t
    from {{ ref('stg_silver_versions') }}
    where not is_seed
),

ordered as (
    select delta_start_t, delta_end_t, lag(delta_end_t) over (order by delta_start_t) as previous_end_t
    from windows
)

select delta_start_t, delta_end_t, previous_end_t
from ordered
where previous_end_t is not null and delta_start_t <> previous_end_t
