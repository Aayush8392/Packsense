{#
  Functions whose name or meaning differs between Databricks and DuckDB, one macro each, dispatched on the adapter.
  iso_weekday: 1 = Monday ... 7 = Sunday on both engines (Databricks `weekday` counts 0 = Monday; DuckDB `isodow` is already ISO).
  weekday_name: English day name. distinct_array_size: number of distinct non-null elements (0 for a NULL array).
#}

{% macro iso_weekday(date_expr) %}{{ return(adapter.dispatch('iso_weekday', 'packsense')(date_expr)) }}{% endmacro %}
{% macro default__iso_weekday(date_expr) %}isodow({{ date_expr }}){% endmacro %}
{% macro databricks__iso_weekday(date_expr) %}(weekday({{ date_expr }}) + 1){% endmacro %}
{% macro duckdb__iso_weekday(date_expr) %}isodow({{ date_expr }}){% endmacro %}

{% macro weekday_name(date_expr) %}{{ return(adapter.dispatch('weekday_name', 'packsense')(date_expr)) }}{% endmacro %}
{% macro default__weekday_name(date_expr) %}dayname({{ date_expr }}){% endmacro %}
{% macro databricks__weekday_name(date_expr) %}date_format({{ date_expr }}, 'EEEE'){% endmacro %}
{% macro duckdb__weekday_name(date_expr) %}dayname({{ date_expr }}){% endmacro %}

{% macro distinct_array_size(array_expr) %}{{ return(adapter.dispatch('distinct_array_size', 'packsense')(array_expr)) }}{% endmacro %}
{% macro default__distinct_array_size(array_expr) %}coalesce(len(list_distinct({{ array_expr }})), 0){% endmacro %}
{% macro databricks__distinct_array_size(array_expr) %}coalesce(size(array_distinct({{ array_expr }})), 0){% endmacro %}
{% macro duckdb__distinct_array_size(array_expr) %}coalesce(len(list_distinct({{ array_expr }})), 0){% endmacro %}
