-- Independent check of the daily change fact: the 'any' rows of scope 'all' must add up to the periods after each product's first, plus the
-- new products (first periods with OFF's revision counter at 1 that did not come from the seed), counted straight from product_history,
-- over the complete days only (the fact leaves out the partial first and newest day).
with firsts as (
    select code, min(valid_from_t) as first_t from {{ ref('product_history') }} group by code
),

bounds as (
    select first_day, last_day from {{ complete_days() }} as cd
)

select expected.n as expected_periods, got.n as fact_periods
from (
    select count(*) as n
    from {{ ref('product_history') }} as h
    inner join firsts as f on f.code = h.code
    cross join bounds as b
    where (h.valid_from_t > f.first_t or (h.rev_at_open = 1 and not h.opened_by_seed))
      and {{ epoch_date('h.valid_from_t') }} between b.first_day and b.last_day
) as expected
cross join (
    select coalesce(sum(n_periods), 0) as n from {{ ref('fct_product_change_daily') }} where scope = 'all' and change_group = 'any'
) as got
where expected.n <> got.n
