-- Internal rules of the card: our checks are at most 11 and never more failed than checked, an error failure is a failure, the seven fields add up, and the
-- light follows its definition exactly (not_enough_data only when nothing is flagged and none of our checks could run).
select code, light, things_flagged, rules_checkable, rules_failed, fields_filled
from {{ ref('mart_product_card') }}
where rules_checkable not between 0 and 11
   or rules_failed > rules_checkable
   or rules_failed_error > rules_failed
   or fields_filled not between 0 and 7
   or fields_filled <> has_nutrition + has_nutriscore + has_nova + has_quantity + has_ingredients + has_categories + has_labels
   or things_flagged <> off_error + off_bug + rules_failed
   or light <> case
        when things_flagged >= {{ var('card_several_from', 2) }} then 'several_flagged'
        when things_flagged >= 1 then 'one_flagged'
        when rules_checkable = 0 then 'not_enough_data'
        else 'none_flagged' end
