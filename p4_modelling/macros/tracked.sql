{#
  The tracked set: a change in any of these opens a new history period (decided 2026-10-17, buildlog block 2b and the gold design).
  Not tracked, on purpose: completeness, popularity_key, unique_scans_n, states_tags, rev (volatile, kept per version in staging),
  last_checked_t, serving_quantity, nutrient_levels_tags (OFF's verdict derived from the nutrients), the data-quality flag tags (their own
  flag-span table), input_sets (per-source breakdown stays in silver), and every hashed contributor column.
  A test in p4_modelling/tests checks these lists against the silver contract.
#}

{% macro tracked_scalars() %}
{{ return([
    'product_name', 'brands',
    'quantity_amount', 'quantity_unit', 'quantity_multiplier', 'serving_amount', 'serving_unit',
    'product_quantity', 'product_quantity_unit', 'ingredients_sha256',
    'pnns_groups_1', 'pnns_groups_2',
    'nutrition_format', 'nutrition_per', 'nutrition_preparation',
    'energy_kj', 'energy_kcal', 'fat', 'saturated_fat', 'carbohydrates', 'sugars', 'added_sugars', 'starch', 'fiber', 'proteins', 'salt', 'sodium',
    'nutriscore_grade', 'nutriscore_score', 'nova_group', 'environmental_score_grade', 'checked'
]) }}
{% endmacro %}

{% macro tracked_arrays() %}
{{ return([
    'categories_tags', 'countries_tags', 'labels_tags', 'allergens_tags', 'traces_tags',
    'additives_tags', 'ingredients_analysis_tags', 'packaging_tags', 'origins_tags', 'food_groups_tags'
]) }}
{% endmacro %}

{# every tracked column, in a fixed order (the nutrients map comes last) #}
{% macro tracked_columns() %}
{{ return(tracked_scalars() + tracked_arrays() + ['nutrients']) }}
{% endmacro %}

{# SHA-256 over the tracked set. Databricks SQL: tag arrays are sorted first, so a pure reordering of the same tags is not a change;
   the nutrients map is turned into entries sorted by key, so key order does not matter either. #}
{% macro tracked_hash() %}
{%- set parts = [] -%}
{%- for c in tracked_scalars() -%}{%- do parts.append("'" ~ c ~ "', " ~ c) -%}{%- endfor -%}
{%- for c in tracked_arrays() -%}{%- do parts.append("'" ~ c ~ "', sort_array(" ~ c ~ ")") -%}{%- endfor -%}
{%- do parts.append("'nutrients', map_from_entries(sort_array(map_entries(nutrients)))") -%}
sha2(to_json(named_struct({{ parts | join(', ') }})), 256)
{% endmacro %}
