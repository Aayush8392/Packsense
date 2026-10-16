-- No duplicate (code, valid_from_t) pair, also after overlapping reruns (the design's snapshot test, done on the derived history).
select code, valid_from_t, count(*) as n
from {{ ref('product_history') }}
group by code, valid_from_t
having count(*) > 1
