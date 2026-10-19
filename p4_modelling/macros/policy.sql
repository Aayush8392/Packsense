{#
  Re-attaches the market row filter (P5 step 4, p5_governance/policies.yml) right after a model builds.
  Why: a dbt build as the owning principal REPLACES the table and that drops the row filter (measured on dev); grants stay, so without this
  the analyst would read every market until the next apply. The statement runs as the gold principal, the table's owner, which holds
  USE SCHEMA and EXECUTE on the policy schema (grants.yml). Not run on DuckDB (no row filters there) and not in the throwaway fixture schema.
  The function name is the one in policies.yml (row_filter_function): p5_governance/tests/test_policies.py ties the two together.
#}
{% macro apply_market_filter(relation, column='market_code') %}
    {%- if target.type == 'databricks' and not var('fixture_mode', false) -%}
        alter table {{ relation }} set row filter {{ var('policy_schema', 'workspace.packsense_policy') }}.market_filter on ({{ column }})
    {%- endif -%}
{% endmacro %}
