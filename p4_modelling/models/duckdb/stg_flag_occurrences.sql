{{ config(materialized='view') }}

-- DuckDB twin of the Databricks view of the same name: one row per version per OFF quality flag. `list_distinct` plays the role of
-- `array_distinct`, `unnest` of `lateral view explode`; a NULL array gives no rows on both engines.
{% set sources = [
    ('error', 'data_quality_errors_tags'),
    ('warning', 'data_quality_warnings_tags'),
    ('info', 'data_quality_info_tags'),
    ('bug', 'data_quality_bugs_tags')
] %}

{% for severity, column in sources %}
select code, last_modified_t, '{{ severity }}' as severity, unnest(list_distinct({{ column }})) as flag
from {{ ref('stg_silver_versions') }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
