{{ config(severity='warn', enabled=(target.type == 'databricks' and not var('fixture_mode', false))) }}
-- Freshness of what gold was built from. OFF's delta files are windows ending about 06:30 UTC; the newest window silver holds must end less
-- than var silver_stale_after_hours (20) ago. Since 2026-10-18 the capture runs first in the 06:45 UTC job and gold runs at 08:15 UTC, so a scheduled day
-- sees silver about 2 hours old (newest window ended about 06:20 UTC) and one skipped day about 26 hours (and warns). 20 rather than 12 so that a MANUAL
-- build later the same day (14 hours or more after the window ended) does not warn. It was 48 when gold ran at 09:30 UTC behind a capture that landed
-- the day before (normal about 27 hours). The threshold is an estimate from the schedule, not a measurement. A WARN on purpose: stale silver is already alerted by
-- packsense-core, this is a second line that shows in the gold run's 'warned:' text. It reads the wall clock, so it is disabled on DuckDB and
-- in the fixture schema (whose dates are old by design).
select max(delta_window_end) as newest_window_end
from {{ ref('stg_silver_versions') }}
where not is_seed
having max(delta_window_end) < current_timestamp() - interval {{ var('silver_stale_after_hours', 20) }} hours
