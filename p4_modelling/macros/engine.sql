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

{#
  first_element: the first element of an array, NULL when the array is NULL or empty (Databricks arrays are read with try_element_at in
  ANSI mode, DuckDB with list_extract). map_get: the value for a key in a map, NULL when the key is absent (ANSI mode raises on a
  missing key with the bracket syntax).
#}
{% macro first_element(array_expr) %}{{ return(adapter.dispatch('first_element', 'packsense')(array_expr)) }}{% endmacro %}
{% macro default__first_element(array_expr) %}list_extract({{ array_expr }}, 1){% endmacro %}
{% macro databricks__first_element(array_expr) %}try_element_at({{ array_expr }}, 1){% endmacro %}
{% macro duckdb__first_element(array_expr) %}list_extract({{ array_expr }}, 1){% endmacro %}

{% macro map_get(map_expr, key) %}{{ return(adapter.dispatch('map_get', 'packsense')(map_expr, key)) }}{% endmacro %}
{% macro default__map_get(map_expr, key) %}element_at({{ map_expr }}, '{{ key }}')[1]{% endmacro %}
{% macro databricks__map_get(map_expr, key) %}try_element_at({{ map_expr }}, '{{ key }}'){% endmacro %}
{% macro duckdb__map_get(map_expr, key) %}element_at({{ map_expr }}, '{{ key }}')[1]{% endmacro %}

{#
  name_key: the normal form two written names are compared in: lower-cased, trimmed, with the combining dot above (U+0307) removed and the Greek
  final sigma folded to the ordinary one. The engines lower-case a few characters differently (Databricks turns the Turkish capital I with dot
  into i plus U+0307, DuckDB into a plain i; Java lower-cases a final sigma by context, DuckDB does not), which made the name lookup differ
  between them for 13 Turkish and Azerbaijani names. Every comparison of written names goes through this macro (a test enforces it).
#}
{% macro name_key(text_expr) %}replace(translate(lower(trim({{ text_expr }})), 'ς', 'σ'), '̇', ''){% endmacro %}

{#
  array_missing_count: how many elements of the first array are not in the second (0 when the first is NULL; the second must not be NULL).
#}
{% macro array_missing_count(first_expr, second_expr) %}{{ return(adapter.dispatch('array_missing_count', 'packsense')(first_expr, second_expr)) }}{% endmacro %}
{% macro default__array_missing_count(first_expr, second_expr) %}coalesce(len(list_filter({{ first_expr }}, x -> not list_contains({{ second_expr }}, x))), 0){% endmacro %}
{% macro databricks__array_missing_count(first_expr, second_expr) %}coalesce(size(array_except({{ first_expr }}, {{ second_expr }})), 0){% endmacro %}
{% macro duckdb__array_missing_count(first_expr, second_expr) %}coalesce(len(list_filter({{ first_expr }}, x -> not list_contains({{ second_expr }}, x))), 0){% endmacro %}

{#
  epoch_date: the UTC calendar day of a Unix time in seconds. Plain arithmetic from 1970-01-01, so the result does not depend on the
  session time zone of either engine (a cast of a timestamp to a date does).
#}
{% macro epoch_date(seconds_expr) %}{{ return(adapter.dispatch('epoch_date', 'packsense')(seconds_expr)) }}{% endmacro %}
{% macro default__epoch_date(seconds_expr) %}(cast('1970-01-01' as date) + cast(floor(({{ seconds_expr }}) / 86400) as integer)){% endmacro %}
{% macro databricks__epoch_date(seconds_expr) %}date_add(cast('1970-01-01' as date), cast(floor(({{ seconds_expr }}) / 86400) as int)){% endmacro %}
{% macro duckdb__epoch_date(seconds_expr) %}(cast('1970-01-01' as date) + cast(floor(({{ seconds_expr }}) / 86400) as integer)){% endmacro %}

