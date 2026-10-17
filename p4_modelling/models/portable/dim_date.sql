{{ config(materialized='table') }}

-- A calendar from OFF's start (2012) to 2035. The weekday is left out on purpose: its function differs between Databricks and DuckDB,
-- so it comes later through a per-engine macro.
select
    cast(extract(year from date_day) * 10000 + extract(month from date_day) * 100 + extract(day from date_day) as integer) as date_key,
    cast(date_day as date) as calendar_date,
    cast(extract(year from date_day) as integer) as year,
    cast(extract(quarter from date_day) as integer) as quarter,
    cast(extract(month from date_day) as integer) as month,
    cast(extract(day from date_day) as integer) as day_of_month,
    cast(extract(year from date_day) * 100 + extract(month from date_day) as integer) as year_month
from (
    {{ dbt.date_spine(datepart='day', start_date="cast('2012-01-01' as date)", end_date="cast('2036-01-01' as date)") }}
) as spine
