{{ config(materialized='table') }}

-- Product history (SCD2), derived from silver's own version history and rebuilt in full on every run (amendment A27).
-- One row per period: a period opens at the first version whose tracked set differs from the previous version's and ends at the
-- next such version. Versions with an unchanged tracked set (no-op versions) are merged into the period they belong to.
-- valid_from_t = the opening version's last_modified_t; valid_to_t = the next period's valid_from_t (NULL on the open row).
-- The open row is `is_latest_observed`, never `is_current`: OFF publishes no deletions, so "latest observed" is all we know.
-- Plain ANSI SQL on purpose (compared against DuckDB); the hashing of the tracked set lives in the Databricks-only staging view.
{% set tracked = tracked_columns() %}

with ordered as (
    select
        code,
        last_modified_t,
        last_modified_ts,
        rev,
        tracked_hash,
        distinct_editors,
        is_seed,
        source_file,
        first_brand,
        {%- for c in tracked %}
        {{ c }},
        {%- endfor %}
        row_number() over (partition by code order by last_modified_t) as version_seq
    from {{ ref('stg_silver_versions') }}
),

lagged as (
    select
        *,
        lag(tracked_hash) over (partition by code order by version_seq) as prev_hash,
        lag(rev) over (partition by code order by version_seq) as prev_rev
    from ordered
),

marked as (
    select
        *,
        case when prev_hash is null or tracked_hash <> prev_hash then 1 else 0 end as is_change,
        -- OFF's rev counts every edit; a jump of more than 1 between two versions we hold means edits we never saw
        case when rev is not null and prev_rev is not null and rev > prev_rev + 1 then rev - prev_rev - 1 else 0 end as unseen_edits
    from lagged
),

numbered as (
    select
        *,
        sum(is_change) over (partition by code order by version_seq rows between unbounded preceding and current row) as period_no
    from marked
),

period_stats as (
    select
        code,
        period_no,
        count(*) as versions_merged,
        sum(unseen_edits) as unseen_edits,
        max(last_modified_t) as last_version_t,
        max(distinct_editors) as distinct_editors
    from numbered
    group by code, period_no
),

opened as (
    select * from numbered where is_change = 1
),

periods as (
    select
        o.code,
        o.period_no,
        o.last_modified_t as valid_from_t,
        o.last_modified_ts as valid_from,
        o.rev as rev_at_open,
        o.is_seed as opened_by_seed,
        o.source_file as opened_by_file,
        o.tracked_hash,
        o.first_brand,
        {%- for c in tracked %}
        o.{{ c }},
        {%- endfor %}
        s.versions_merged,
        s.unseen_edits,
        s.last_version_t,
        s.distinct_editors
    from opened o
    inner join period_stats s on o.code = s.code and o.period_no = s.period_no
)

select
    {{ dbt.hash(dbt.concat(['code', "'|'", dbt.safe_cast('valid_from_t', dbt.type_string())])) }} as history_key,
    p.*,
    {{ dbt.hash('first_brand') }} as brand_key,
    lead(valid_from_t) over (partition by code order by period_no) as valid_to_t,
    lead(valid_from) over (partition by code order by period_no) as valid_to,
    case when lead(valid_from_t) over (partition by code order by period_no) is null then 1 else 0 end as is_latest_observed
from periods p
