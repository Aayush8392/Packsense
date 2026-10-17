-- A span starts before it ends, a flag vanishes after its last sighting, and an open span has no vanish time.
select flag_id
from {{ ref('product_flag_spans') }}
where first_seen_t > last_seen_t
   or (vanished_at_t is not null and vanished_at_t <= last_seen_t)
   or (is_open = 1 and vanished_at_t is not null)
   or (is_open = 0 and vanished_at_t is null)
