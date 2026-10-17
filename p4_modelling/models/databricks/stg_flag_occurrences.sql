{{ config(materialized='view') }}

-- One row per version per OFF quality flag. Databricks-only because it explodes the four flag arrays; the logic that turns these rows
-- into spans lives in the portable model product_flag_spans. The flag is the raw OFF tag for now; mapping tags to OFF's check
-- families waits for the taxonomy loader. array_distinct guards against a tag listed twice in one version.
{% set sources = [
    ('error', 'data_quality_errors_tags'),
    ('warning', 'data_quality_warnings_tags'),
    ('info', 'data_quality_info_tags'),
    ('bug', 'data_quality_bugs_tags')
] %}

{% for severity, column in sources %}
select code, last_modified_t, '{{ severity }}' as severity, flag
from {{ ref('stg_silver_versions') }}
lateral view explode(array_distinct({{ column }})) exploded as flag
{% if not loop.last %}union all{% endif %}
{% endfor %}
