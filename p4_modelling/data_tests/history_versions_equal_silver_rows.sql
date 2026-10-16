-- Nothing lost, nothing counted twice: the versions merged across all periods equal the silver rows.
select merged.n_merged, staged.n_rows
from (select sum(versions_merged) as n_merged from {{ ref('product_history') }}) as merged
cross join (select count(*) as n_rows from {{ ref('stg_silver_versions') }}) as staged
where merged.n_merged <> staged.n_rows
