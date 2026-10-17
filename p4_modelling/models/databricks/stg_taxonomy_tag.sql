{{ config(materialized='view') }}

-- Staging over silver's taxonomy table (one row per taxonomy, snapshot and tag). Databricks-only because it reads the silver source; the
-- DuckDB twin reads the committed fixture. Lineage columns that change per run (loaded_at, job_run_id) are left out on purpose.
{% if var('fixture_mode', false) %}
-- Fixture mode (the throwaway verification schema only): the committed fixture is this view's output for a chosen real slice.
select * from {{ source('fixture', 'fixture_taxonomy_tag') }}
{% else %}
select taxonomy, tag, snapshot, snapshot_sha256, valid_from, name_en, names, parents, children, props
from {{ source('silver', 'silver_taxonomy_tag') }}
{% endif %}
