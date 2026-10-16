-- A period ends exactly where the next one starts, and time moves forward.
select code, valid_from_t, valid_to_t
from {{ ref('product_history') }}
where valid_to_t is not null and valid_to_t <= valid_from_t
