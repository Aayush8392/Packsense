{{ config(materialized='view') }}

-- One row per taxonomy tag and language name, from the newest snapshots gold uses. Databricks-only: the map explode is engine-specific;
-- the lookup built on it is portable.
select t.taxonomy, t.tag, e.lang, e.name_text
from {{ ref('taxonomy_tag_latest') }} as t
lateral view explode(t.names) e as lang, name_text
