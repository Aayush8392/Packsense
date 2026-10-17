{#
  complete_days: the first and last UTC day that our delta files cover completely (decided 2026-10-18, measured on production silver).
  OFF's delta files run from about 06:20-06:35 UTC to the same time the next day, so a calendar day is split across two files. The first
  day (before the first file's window starts) and the newest day (after the newest file's window ends) are therefore partial: on
  production 30 Sep had only the edits after 06:17 and 16 Oct had 762 edits against 5,000 to 8,000 on a full day. A day counts only when
  its whole 24 hours lie inside the covered window: first_day = the first midnight at or after the earliest window start, last_day = the
  day before the last midnight at or before the latest window end. The seed is excluded (its rows carry no window). Used by the two
  daily facts, which show only complete days; a day becomes complete when the next capture lands.
  Usage: cross join {{ complete_days() }} as cd, then cd.first_day and cd.last_day.
#}
{% macro complete_days() %}
(
    select
        {{ epoch_date('ceil(min(delta_start_t) / 86400.0) * 86400') }} as first_day,
        {{ epoch_date('floor(max(delta_end_t) / 86400.0) * 86400 - 86400') }} as last_day
    from {{ ref('stg_silver_versions') }}
    where not is_seed
)
{% endmacro %}
