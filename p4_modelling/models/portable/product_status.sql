{{ config(materialized='incremental', unique_key='code') }}

-- Whether a product still exists on OFF. OFF publishes no deletions, so every product starts `unverified`; the monthly deletion
-- reconciliation (P9) fills status, checked_at and evidence_source. This model only ever INSERTS codes it has not seen: it never
-- touches an existing row, so a filled-in status survives every nightly run. Nothing in gold may read 'unverified' as 'exists'.
select
    code,
    'unverified' as status,
    cast(null as {{ dbt.type_timestamp() }}) as checked_at,
    cast(null as {{ dbt.type_string() }}) as evidence_source
from (select distinct code from {{ ref('stg_silver_versions') }}) as codes
{% if is_incremental() %}
where code not in (select code from {{ this }})
{% endif %}
