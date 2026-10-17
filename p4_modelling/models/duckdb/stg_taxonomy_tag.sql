{{ config(materialized='view') }}

-- DuckDB twin of the Databricks staging view: reads the committed fixture, which is that view's output for a chosen real slice.
select * from {{ source('fixture', 'fixture_taxonomy_tag') }}
