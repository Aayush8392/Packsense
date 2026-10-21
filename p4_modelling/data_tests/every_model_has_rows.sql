-- Volume floor (P4 closing checks, 2026-10-18): every portable model must hold at least one row. A model that builds empty (an upstream filter
-- that matches nothing, a macro that returns no days) passes every shape test, so this is the check that notices. The list below is the 21
-- models of the engine comparison; tests/test_checks.py fails when a model is added to gold_lib/compare.py and not listed here.
{% set models = [
    'product_history', 'product_flag_spans', 'product_status', 'product_nutrition_sets', 'dim_brand', 'dim_market', 'bridge_product_market', 'dim_date', 'dim_flag',
    'taxonomy_tag_latest', 'bridge_product_allergen', 'dim_allergen', 'taxonomy_name_lookup', 'mart_allergen_change_log',
    'bridge_product_category', 'dim_category', 'bridge_product_label', 'dim_label', 'fct_product_change_daily',
    'fct_catalogue_quality_daily', 'mart_brand_scorecard'
] %}
{% for m in models %}
select '{{ m }}' as model from (select count(*) as n from {{ ref(m) }}) as c where c.n = 0
{% if not loop.last %}union all{% endif %}
{% endfor %}
