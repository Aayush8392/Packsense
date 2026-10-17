{{ config(materialized='table') }}

-- OFF's quality flags as spans: one row per product, flag and unbroken run of versions that carry it. Kept apart from the history
-- table on purpose: the triage labels need "the flag appeared at version k and vanished at version m, with a value change".
-- A flag that vanishes and comes back is two spans. Rebuilt in full every run; plain ANSI SQL.
--   first_seen_is_first_version = 1 : we never saw this product without the flag (it may have been there from creation or from the
--                                     seed), so "the flag appeared at first_seen_t" must not be claimed for it.
--   is_open = 1                      : the product's newest observed version still carries the flag.
--   vanished_with_tracked_change     : the version that dropped the flag also changed the tracked set (NULL while open).
-- flag_id is a hash of (code, severity, flag, first_seen_t): the same inputs give the same id after a rebuild.
with versions as (
    select
        code,
        last_modified_t,
        tracked_hash,
        row_number() over (partition by code order by last_modified_t) as version_seq
    from {{ ref('stg_silver_versions') }}
),

occurrences as (
    select o.code, o.severity, o.flag, v.version_seq, v.last_modified_t
    from {{ ref('stg_flag_occurrences') }} as o
    inner join versions as v on o.code = v.code and o.last_modified_t = v.last_modified_t
),

islands as (
    select
        code,
        severity,
        flag,
        version_seq,
        last_modified_t,
        version_seq - row_number() over (partition by code, severity, flag order by version_seq) as island
    from occurrences
),

spans as (
    select
        code,
        severity,
        flag,
        island,
        min(version_seq) as first_seq,
        max(version_seq) as last_seq,
        min(last_modified_t) as first_seen_t,
        max(last_modified_t) as last_seen_t,
        count(*) as versions_present
    from islands
    group by code, severity, flag, island
)

select
    {{ dbt.hash(dbt.concat(['s.code', "'|'", 's.severity', "'|'", 's.flag', "'|'", dbt.safe_cast('s.first_seen_t', dbt.type_string())])) }} as flag_id,
    s.code,
    s.severity,
    s.flag,
    s.first_seen_t,
    s.last_seen_t,
    s.versions_present,
    case when s.first_seq = 1 then 1 else 0 end as first_seen_is_first_version,
    nxt.last_modified_t as vanished_at_t,
    case when nxt.last_modified_t is null then 1 else 0 end as is_open,
    case
        when nxt.last_modified_t is null then null
        when nxt.tracked_hash <> lst.tracked_hash then 1
        else 0
    end as vanished_with_tracked_change
from spans as s
inner join versions as lst on s.code = lst.code and s.last_seq = lst.version_seq
left join versions as nxt on s.code = nxt.code and s.last_seq + 1 = nxt.version_seq
