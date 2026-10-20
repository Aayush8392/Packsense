{{ config(materialized='view') }}

-- Staging over silver's existence checks (one row per product per check: a snapshot row from the weekly snapshot comparison, or an answer from OFF's API;
-- p9_operations/existence_lib.py says what each status means). Databricks-only because it reads the silver source; the DuckDB twin reads the committed
-- fixture. The lineage columns (snapshot_sha, job_run_id) are left out on purpose: gold needs what was found, when and on what evidence, not which run.
{% if var('fixture_mode', false) %}
-- Fixture mode (the throwaway verification schema only): the committed fixture is this view's output for the fixture products.
select * from {{ source('fixture', 'fixture_existence_check') }}
{% else %}
select code, checked_at, status, detail, evidence_source
from {{ source('silver', 'silver_existence_check') }}
{% endif %}
