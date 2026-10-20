{{ config(materialized='view') }}

-- DuckDB twin of the Databricks staging view: reads the committed fixture, which is that view's output for the fixture products.
select * from {{ source('fixture', 'fixture_existence_check') }}
