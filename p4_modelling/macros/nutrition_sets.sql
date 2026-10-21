{#
  A nutrient value of an input set in grams. `entry` is the SQL text of the map entry (a struct with value and unit), e.g. "s.nutrients['salt']". Each entry carries its
  own unit (measured 2026-10-21 on 20,000 products: salt and sodium are in milligrams in about 7% of the sets, a median of 700 times the gram value). A mass in g, mg,
  micrograms or kg is converted; any other unit (or none) gives NULL, never a number in the wrong unit. Energy is not a mass and is read without this macro.
#}
{% macro grams(entry) -%}
cast(case
    when {{ entry }}.unit = 'g' then {{ entry }}.value
    when {{ entry }}.unit = 'mg' then {{ entry }}.value / 1000.0
    when {{ entry }}.unit in ('µg', 'μg', 'mcg', 'ug') then {{ entry }}.value / 1000000.0
    when {{ entry }}.unit = 'kg' then {{ entry }}.value * 1000.0
end as double)
{%- endmacro %}
