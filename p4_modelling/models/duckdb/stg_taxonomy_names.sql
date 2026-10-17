{{ config(materialized='view') }}

-- DuckDB twin of the Databricks view of the same name: the two unnests over map_keys and map_values are zipped (same length).
select t.taxonomy, t.tag, unnest(map_keys(t.names)) as lang, unnest(map_values(t.names)) as name_text
from {{ ref('taxonomy_tag_latest') }} as t
