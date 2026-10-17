{#
  The change groups of fct_product_change_daily (slice 5, decided 2026-10-18): which tracked columns a reader means by "the name changed",
  "the nutrition changed" and so on. Every tracked column (macros/tracked.sql) belongs to exactly one group; a test in tests/ checks that the
  groups and the tracked set cover the same columns. A history period opens when the tracked set changes, so each period after a product's
  first is in at least one group.
#}

{% macro change_groups() %}
{{ return({
    'name_brand': ['product_name', 'brands'],
    'quantity': ['quantity_amount', 'quantity_unit', 'quantity_multiplier', 'serving_amount', 'serving_unit', 'product_quantity', 'product_quantity_unit'],
    'nutrition': ['nutrition_format', 'nutrition_per', 'nutrition_preparation', 'energy_kj', 'energy_kcal', 'fat', 'saturated_fat', 'carbohydrates', 'sugars', 'added_sugars', 'starch', 'fiber', 'proteins', 'salt', 'sodium', 'nutrients'],
    'nutriscore_nova': ['nutriscore_grade', 'nutriscore_score', 'nova_group', 'environmental_score_grade'],
    'ingredients': ['ingredients_sha256', 'ingredients_analysis_tags', 'additives_tags'],
    'allergens': ['allergens_tags', 'traces_tags'],
    'categories_labels': ['categories_tags', 'labels_tags', 'pnns_groups_1', 'pnns_groups_2', 'food_groups_tags'],
    'other_tags': ['countries_tags', 'packaging_tags', 'origins_tags', 'checked']
}) }}
{% endmacro %}

{#
  sorted_array / sorted_map_entries: the normal form two tag arrays (or two nutrient maps) are compared in, so a pure reordering is not a
  change; this is the same rule the tracked hash applies in the Databricks staging view. NULL stays different from an empty array there too.
#}
{% macro sorted_array(array_expr) %}{{ return(adapter.dispatch('sorted_array', 'packsense')(array_expr)) }}{% endmacro %}
{% macro default__sorted_array(array_expr) %}list_sort({{ array_expr }}){% endmacro %}
{% macro databricks__sorted_array(array_expr) %}sort_array({{ array_expr }}){% endmacro %}
{% macro duckdb__sorted_array(array_expr) %}list_sort({{ array_expr }}){% endmacro %}

{% macro sorted_map_entries(map_expr) %}{{ return(adapter.dispatch('sorted_map_entries', 'packsense')(map_expr)) }}{% endmacro %}
{% macro default__sorted_map_entries(map_expr) %}list_sort(map_entries({{ map_expr }})){% endmacro %}
{% macro databricks__sorted_map_entries(map_expr) %}sort_array(map_entries({{ map_expr }})){% endmacro %}
{% macro duckdb__sorted_map_entries(map_expr) %}list_sort(map_entries({{ map_expr }})){% endmacro %}

{# column_differs: SQL that is true when the column differs between the current period c and the previous period p. #}
{% macro column_differs(col) %}
{%- if col in tracked_arrays() -%}
{{ sorted_array('c.' ~ col) }} is distinct from {{ sorted_array('p.' ~ col) }}
{%- elif col == 'nutrients' -%}
{{ sorted_map_entries('c.' ~ col) }} is distinct from {{ sorted_map_entries('p.' ~ col) }}
{%- else -%}
c.{{ col }} is distinct from p.{{ col }}
{%- endif -%}
{% endmacro %}
