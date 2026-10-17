-- One tag cannot be both added and removed in the same change of the same product and relationship.
select code, changed_at_t, relationship, allergen_tag
from {{ ref('mart_allergen_change_log') }}
group by code, changed_at_t, relationship, allergen_tag
having count(distinct change_type) > 1
