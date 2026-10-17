{{ config(materialized='table') }}

-- One row per distinct OFF quality flag seen in the flag spans, with its place in OFF's data_quality taxonomy (newest snapshot).
-- family = the flag's first parent tag (parents are sorted, so the choice is deterministic; 4 of 1,248 taxonomy tags have two parents).
-- family_source says how far to trust it:
--   taxonomy : the flag is in the taxonomy and has a parent (the family),
--   root     : the flag is itself a top-level tag of the taxonomy (no parent),
--   unmapped : the flag is NOT in the taxonomy. OFF generates many flags in code (the per-source nutrition checks, for one), so they
--              never appear in the taxonomy file. Measured on production 2026-10-17: 477 of 779 distinct flags are in the taxonomy,
--              which covers 94% of the 1.09 million spans. No family is guessed for the rest.
-- A flag is NOT one severity: OFF files the same tag under different severities for different products or at different times (seen:
-- en:nutrition-value-total-over-105 is a warning on two products and an error on a third). So the dimension carries has_error,
-- has_warning, has_info and has_bug (1 when any span of the flag has that severity) and n_severities; the severity of a span is in
-- product_flag_spans.
with flags as (
    select
        flag,
        max(case when severity = 'error' then 1 else 0 end) as has_error,
        max(case when severity = 'warning' then 1 else 0 end) as has_warning,
        max(case when severity = 'info' then 1 else 0 end) as has_info,
        max(case when severity = 'bug' then 1 else 0 end) as has_bug,
        count(distinct severity) as n_severities
    from {{ ref('product_flag_spans') }}
    group by flag
),

base as (
    select
        f.flag,
        f.has_error,
        f.has_warning,
        f.has_info,
        f.has_bug,
        f.n_severities,
        t.tag as taxonomy_tag,
        t.name_en,
        t.parents as parent_tags,
        {{ first_element('t.parents') }} as family
    from flags as f
    left join {{ ref('taxonomy_tag_latest') }} as t on t.taxonomy = 'data_quality' and t.tag = f.flag
)

select
    b.flag,
    coalesce(b.name_en, b.flag) as flag_name,
    b.has_error,
    b.has_warning,
    b.has_info,
    b.has_bug,
    b.n_severities,
    case when b.taxonomy_tag is null then 0 else 1 end as in_taxonomy,
    b.parent_tags,
    b.family,
    coalesce(fam.name_en, b.family) as family_name,
    case
        when b.taxonomy_tag is null then 'unmapped'
        when b.family is null then 'root'
        else 'taxonomy'
    end as family_source
from base as b
left join {{ ref('taxonomy_tag_latest') }} as fam on fam.taxonomy = 'data_quality' and fam.tag = b.family
