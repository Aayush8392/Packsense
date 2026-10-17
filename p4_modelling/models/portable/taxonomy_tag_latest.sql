{{ config(materialized='table') }}

-- The newest snapshot of each taxonomy gold uses (var gold_taxonomies). The whole newest snapshot is taken, not the newest row of each
-- tag, so a tag OFF has since removed does not live on. Older snapshots stay in silver for "which taxonomy was in force on day d".
select
    t.taxonomy,
    t.tag,
    t.valid_from as snapshot_valid_from,
    t.name_en,
    t.names,
    t.parents,
    t.children,
    t.props
from {{ ref('stg_taxonomy_tag') }} as t
inner join (
    select taxonomy, max(valid_from) as valid_from
    from {{ ref('stg_taxonomy_tag') }}
    group by taxonomy
) as newest on t.taxonomy = newest.taxonomy and t.valid_from = newest.valid_from
where t.taxonomy in ({% for name in var('gold_taxonomies') %}'{{ name }}'{% if not loop.last %}, {% endif %}{% endfor %})
