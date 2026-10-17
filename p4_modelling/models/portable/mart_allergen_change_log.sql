{{ config(materialized='table') }}

-- The allergen change log (design section 4, "allergen and ingredient change alerts" for food safety): for every product and every pair of
-- consecutive history periods, which allergen tags were added or removed, per relationship. A period opens only when the tracked set
-- changes, and allergens_tags and traces_tags are both in it, so an allergen change always starts a new period; periods that changed
-- something else give no rows here (their allergen sets are equal). The first period of a product has no predecessor, so no rows: its
-- allergens are the starting state, not a change. valid_to_t of one period equals valid_from_t of the next (a tested property of the history).
with pairs as (
    select p.history_key as prev_key, c.history_key as curr_key, c.code, c.valid_from_t as changed_at_t, c.valid_from as changed_at
    from {{ ref('product_history') }} as p
    inner join {{ ref('product_history') }} as c on p.code = c.code and p.valid_to_t = c.valid_from_t
),

changes as (
    select pr.code, pr.changed_at_t, pr.changed_at, b.relationship, b.allergen_tag, 'added' as change_type
    from pairs as pr
    inner join {{ ref('bridge_product_allergen') }} as b on b.history_key = pr.curr_key
    left join {{ ref('bridge_product_allergen') }} as bp
        on bp.history_key = pr.prev_key and bp.relationship = b.relationship and bp.allergen_tag = b.allergen_tag
    where bp.history_key is null
    union all
    select pr.code, pr.changed_at_t, pr.changed_at, b.relationship, b.allergen_tag, 'removed' as change_type
    from pairs as pr
    inner join {{ ref('bridge_product_allergen') }} as b on b.history_key = pr.prev_key
    left join {{ ref('bridge_product_allergen') }} as bc
        on bc.history_key = pr.curr_key and bc.relationship = b.relationship and bc.allergen_tag = b.allergen_tag
    where bc.history_key is null
)

select
    {{ dbt.hash(dbt.concat(['code', "'|'", dbt.safe_cast('changed_at_t', dbt.type_string()), "'|'", 'relationship', "'|'", 'allergen_tag', "'|'", 'change_type'])) }} as change_key,
    code,
    changed_at_t,
    changed_at,
    relationship,
    allergen_tag,
    change_type
from changes
