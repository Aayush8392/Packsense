{{ config(severity='warn', enabled=(target.type == 'databricks' and not var('fixture_mode', false))) }}
-- The weekly snapshot comparison (Tuesdays 07:00 UTC) writes a `present_in_snapshot` row per product; the newest one must be less than
-- var existence_stale_after_days (10) old. A normal week sees it 13 hours old at the 08:15 UTC gold run and at most 7.5 days old just before the next
-- one; 10 leaves room for one late run and warns when a whole week was missed. An EMPTY table warns too. A WARN on purpose: it shows in the gold run's
-- 'warned:' text and does not stop the build. It reads the wall clock, so it is disabled on DuckDB and in the fixture schema (whose dates are old by design).
select max(checked_at) as newest_present_check
from {{ ref('stg_existence_check') }}
where status = 'present_in_snapshot'
having coalesce(max(checked_at), cast('1970-01-01' as timestamp)) < current_timestamp() - interval {{ var('existence_stale_after_days', 10) }} days
