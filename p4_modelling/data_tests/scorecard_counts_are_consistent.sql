-- Internal rules of the brand scorecard: no count above the number of products, coverage_points is the sum of the seven counts, the ranked
-- flag follows the floor (and never a product-less or unnamed brand), a brand's India products never exceed its all-market products, and the
-- spans held by the scorecard equal the open spans counted straight from product_flag_spans on the scorecard's day.
with c as (
    select * from {{ ref('mart_brand_scorecard') }}
),

day as (
    select max(as_of_date) as d from c
),

bad_rows as (
    select scorecard_key, 'a count is above n_products' as what
    from c
    where n_with_nutrition > n_products or n_with_nutriscore > n_products or n_with_nova > n_products or n_with_quantity > n_products
       or n_with_ingredients > n_products or n_with_categories > n_products or n_with_labels > n_products
       or n_products_with_error_flag > n_products or n_products_with_error_flag > open_error_spans
    union all
    select scorecard_key, 'coverage_points is not the sum'
    from c
    where coverage_points <> n_with_nutrition + n_with_nutriscore + n_with_nova + n_with_quantity + n_with_ingredients + n_with_categories + n_with_labels
    union all
    select scorecard_key, 'is_ranked does not follow the floor'
    from c
    where is_ranked <> case when brand_name <> '(no brand)' and n_products >= {{ var('scorecard_min_products', 30) }} then 1 else 0 end
    union all
    select scorecard_key, 'a negative count'
    from c
    where n_products < 1 or open_error_spans < 0 or open_warning_spans < 0
    union all
    select i.scorecard_key, 'india above all'
    from c as i
    left join c as a on a.scope = 'all' and a.brand_name = i.brand_name
    where i.scope = 'india' and (a.scorecard_key is null or i.n_products > a.n_products)
),

span_check as (
    select 'open spans differ from product_flag_spans' as what,
           coalesce(sum(case when scope = 'all' then open_error_spans + open_warning_spans end), 0) as got,
           (select count(*) from {{ ref('product_flag_spans') }} as s cross join day as dd
             where s.severity in ('error', 'warning')
               and {{ epoch_date('s.first_seen_t') }} <= dd.d
               and (s.vanished_at_t is null or {{ epoch_date('s.vanished_at_t') }} > dd.d)) as expected
    from c
)

select scorecard_key as detail, what from bad_rows
union all
select cast(expected as {{ dbt.type_string() }}) || ' vs ' || cast(got as {{ dbt.type_string() }}) as detail, what
from span_check where got <> expected
