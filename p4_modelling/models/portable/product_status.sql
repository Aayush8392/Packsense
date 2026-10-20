{{ config(materialized='table') }}

-- Whether each product we hold is still in OFF's food database, as of its latest existence check (silver_existence_check; the weekly snapshot comparison
-- and the Airflow lookups of OFF's API write it). One row per product of the history. A product with no check yet is `unverified`, and nothing in gold may
-- read 'unverified' as 'exists'. Until 2026-10-21 this was an insert-only table of `unverified` rows; it is rebuilt in full each night now, because the
-- memory lives in the (append-only) silver table, which keeps every check.
--   latest check = the newest `checked_at`; at the same instant an API answer beats a snapshot row (the API asked about this very product).
--   status       one of unverified, present_in_snapshot, confirmed_exists, confirmed_not_found, moved_other_type, invalid_code, unconfirmed
--   detail       what OFF said beyond the status, e.g. `beauty` when OFF moved the product to Open Beauty Facts; NULL otherwise
with latest as (
    select
        code,
        status,
        detail,
        checked_at,
        evidence_source,
        row_number() over (
            partition by code
            order by checked_at desc, case when evidence_source = 'off_api_v2' then 0 else 1 end
        ) as rn
    from {{ ref('stg_existence_check') }}
)

select
    h.code,
    coalesce(l.status, 'unverified') as status,
    l.detail,
    l.checked_at,
    l.evidence_source
from (select distinct code from {{ ref('stg_silver_versions') }}) as h
left join latest as l on h.code = l.code and l.rn = 1
