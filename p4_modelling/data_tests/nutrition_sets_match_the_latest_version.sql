-- The table holds the latest version of each product only, and exactly its sets: the number of rows per product equals the size of the latest version's input_sets,
-- and a product with no input sets has no rows.
with latest as (
    select code, last_modified_t, coalesce({{ 'len' if target.type == 'duckdb' else 'size' }}(input_sets), 0) as n_sets
    from (
        select code, last_modified_t, input_sets, row_number() over (partition by code order by last_modified_t desc) as rn
        from {{ ref('stg_silver_versions') }}
    ) as ranked
    where rn = 1
),

built as (
    select code, last_modified_t, count(*) as n_rows
    from {{ ref('product_nutrition_sets') }}
    group by code, last_modified_t
)

select l.code, l.last_modified_t, l.n_sets, coalesce(b.n_rows, 0) as n_rows
from latest as l
left join built as b on l.code = b.code and l.last_modified_t = b.last_modified_t
where l.n_sets <> coalesce(b.n_rows, 0)
union all
select b.code, b.last_modified_t, 0, b.n_rows
from built as b
left join latest as l on b.code = l.code and b.last_modified_t = l.last_modified_t
where l.code is null
