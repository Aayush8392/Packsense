{{ config(severity='warn', enabled=(target.type == 'databricks' and not var('fixture_mode', false))) }}
-- Freshness of what gold was built from. OFF's delta files are windows ending about 06:30 UTC; the newest window silver holds must end less
-- than var silver_stale_after_hours (48) ago. A normal day at the 09:30 UTC gold run is about 27 hours; one skipped day is about 51 and warns.
-- The threshold is an estimate from the observed schedule, not a measurement. A WARN on purpose: stale silver is already alerted by
-- packsense-core, this is a second line that shows in the gold run's 'warned:' text. It reads the wall clock, so it is disabled on DuckDB and
-- in the fixture schema (whose dates are old by design).
select max(delta_window_end) as newest_window_end
from {{ ref('stg_silver_versions') }}
where not is_seed
having max(delta_window_end) < current_timestamp() - interval {{ var('silver_stale_after_hours', 48) }} hours
