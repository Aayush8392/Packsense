{#
  Replay (roadmap item 6): the catalogue as we held it at the END of a UTC day d (a date, e.g. from epoch_date), rebuilt from the history
  and the flag spans with no extra table. These two predicates are the single definition; p7_triage_ml/replay_lib.py carries the same
  rule in seconds and a test keeps the two in step.
    history_as_of(d, alias): the period that was open at the end of d (valid_from on or before d, valid_to empty or after d).
    spans_as_of(d, alias):   the flag spans that were open at the end of d (first seen on or before d, not vanished by d).
  Nothing dated after d can satisfy either predicate: that is the leakage guard a detector or the steward relies on.
#}
{% macro history_as_of(d, alias='h') %}
({{ epoch_date(alias ~ '.valid_from_t') }} <= {{ d }} and ({{ alias }}.valid_to_t is null or {{ epoch_date(alias ~ '.valid_to_t') }} > {{ d }}))
{% endmacro %}

{% macro spans_as_of(d, alias='s') %}
({{ epoch_date(alias ~ '.first_seen_t') }} <= {{ d }} and ({{ alias }}.vanished_at_t is null or {{ epoch_date(alias ~ '.vanished_at_t') }} > {{ d }}))
{% endmacro %}
