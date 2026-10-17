-- One row per (taxonomy, tag) in the newest-snapshot table: a duplicate would double every join to it.
select taxonomy, tag, count(*) as n
from {{ ref('taxonomy_tag_latest') }}
group by taxonomy, tag
having count(*) > 1
