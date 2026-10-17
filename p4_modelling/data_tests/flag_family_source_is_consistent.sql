-- family_source agrees with the columns it describes: an unmapped flag is not in the taxonomy and has no family; a root has none; a taxonomy flag has one.
select flag, family_source, in_taxonomy
from {{ ref('dim_flag') }}
where (family_source = 'unmapped' and (in_taxonomy <> 0 or family is not null))
   or (family_source = 'root' and (in_taxonomy <> 1 or family is not null))
   or (family_source = 'taxonomy' and (in_taxonomy <> 1 or family is null))
