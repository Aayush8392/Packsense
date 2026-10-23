-- versions_kept equals the number of silver versions of the product counted straight from the staging view (not from the history's merged counts).
with silver as (
    select code, count(*) as n from {{ ref('stg_silver_versions') }} group by code
)
select c.code, c.versions_kept, s.n
from {{ ref('mart_product_card') }} as c
left join silver as s on s.code = c.code
where s.n is null or c.versions_kept <> s.n
