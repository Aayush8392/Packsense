{{ config(severity='warn') }}
-- Volume memory without any extra state: product_status is insert-only, so it holds every product the build has ever seen in silver. The
-- history is rebuilt in full each night from silver, so it can never hold FEWER distinct products than the status table. If it does, silver
-- lost products (a restore to an older version, a bad run). A WARN: after a deliberate rollback the status table is the one to reconcile,
-- and gold should still build while someone looks.
select h.n as products_in_history, s.n as products_in_status
from (select count(distinct code) as n from {{ ref('product_history') }}) as h
cross join (select count(*) as n from {{ ref('product_status') }}) as s
where h.n < s.n
