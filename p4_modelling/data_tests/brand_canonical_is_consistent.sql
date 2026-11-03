-- Checks of the canonical brand map that do not depend on how the key is written: (1) there is one row per dim_brand row; (2) a canonical spelling maps to
-- itself (no chain: the colombia / colombina case of review 14 cannot happen through this table); (3) the canonical's own row is 'same' and the rows of a group
-- agree on one canonical; (4) the table never makes more canonical brands than dim_brand has brands.
select 'row_count' as problem, cast(count(*) as bigint) as n
from {{ ref('dim_brand_canonical') }} as c
having count(*) <> (select count(*) from {{ ref('dim_brand') }})

union all

select 'canonical_not_self_mapped' as problem, count(*) as n
from {{ ref('dim_brand_canonical') }} as c
inner join {{ ref('dim_brand_canonical') }} as t on t.brand_key = c.canonical_brand_key
where t.canonical_brand_key <> t.brand_key or t.merge_rule <> 'same'
having count(*) > 0

union all

select 'canonical_row_not_same' as problem, count(*) as n
from {{ ref('dim_brand_canonical') }} as c
where c.brand_key = c.canonical_brand_key and c.merge_rule <> 'same'
having count(*) > 0

union all

select 'more_canonicals_than_brands' as problem, count(distinct canonical_brand_key) as n
from {{ ref('dim_brand_canonical') }}
having count(distinct canonical_brand_key) > (select count(*) from {{ ref('dim_brand') }})
