{{ config(materialized='table') }}

-- The day table MetricFlow needs to line metrics up on dates. DuckDB only (the semantic layer is checked on the fixture, not run on Databricks; see the README).
select cast(d as date) as date_day
from generate_series(date '2026-01-01', date '2027-12-31', interval 1 day) as t(d)
