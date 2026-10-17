{{ config(materialized='view') }}

-- DuckDB twin of the Databricks staging view. DuckDB cannot run the Databricks staging (sort_array, sha2, timestamp_seconds, ...),
-- so this reads the committed fixture, which IS that view's output for a chosen real slice, including the columns that need
-- Databricks functions (tracked_hash, first_brand, GTIN-14, check digit, distinct_editors). tracked_hash is therefore carried, not
-- recomputed here; the portable models are what the comparison tests.
select * from {{ source('fixture', 'fixture_stg_silver_versions') }}
