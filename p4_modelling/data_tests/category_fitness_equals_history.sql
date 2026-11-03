-- Independent check of the category fitness mart: per scope, the product, five-nutrient, ingredients and quantity totals must equal the same counts
-- taken a different way from product_history (the newest period of each product with a start on or before as_of_date, by row_number, not by the
-- interval test the model uses), and the product total must equal the brand scorecard's for the same scope. The 28-day and 365-day columns are
-- checked against a pure-Python count in tests/test_category_fitness.py (date windows are the part that needs a second formulation outside SQL).
with day as (
    select max(as_of_date) as d from {{ ref('mart_category_fitness') }}
),

newest as (
    select h.code, h.energy_kcal, h.fat, h.carbohydrates, h.proteins, h.salt, h.quantity_amount, h.ingredients_sha256,
           row_number() over (partition by h.code order by h.valid_from_t desc) as rn
    from {{ ref('product_history') }} as h cross join day as dd
    where {{ epoch_date('h.valid_from_t') }} <= dd.d
),

india as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

picked as (
    select 'all' as scope, n.* from newest as n where n.rn = 1
    union all
    select 'india' as scope, n.* from newest as n inner join india as i on i.code = n.code where n.rn = 1
),

expected as (
    select
        scope,
        count(*) as n_products,
        sum(case when energy_kcal is not null and fat is not null and carbohydrates is not null and proteins is not null and salt is not null then 1 else 0 end) as n_five_nutrients,
        sum(case when ingredients_sha256 is not null then 1 else 0 end) as n_with_ingredients,
        sum(case when quantity_amount is not null then 1 else 0 end) as n_with_quantity
    from picked
    group by scope
),

got as (
    select scope, sum(n_products) as n_products, sum(n_five_nutrients) as n_five_nutrients, sum(n_with_ingredients) as n_with_ingredients,
           sum(n_with_quantity) as n_with_quantity
    from {{ ref('mart_category_fitness') }}
    group by scope
),

brands as (
    select scope, sum(n_products) as n_products from {{ ref('mart_brand_scorecard') }} group by scope
)

select e.scope, 'history' as against, e.n_products as expected, coalesce(g.n_products, 0) as got
from expected as e left join got as g on g.scope = e.scope
where e.n_products <> coalesce(g.n_products, 0) or e.n_five_nutrients <> coalesce(g.n_five_nutrients, 0)
   or e.n_with_ingredients <> coalesce(g.n_with_ingredients, 0) or e.n_with_quantity <> coalesce(g.n_with_quantity, 0)

union all

select b.scope, 'scorecard' as against, b.n_products as expected, coalesce(g.n_products, 0) as got
from brands as b left join got as g on g.scope = b.scope
where b.n_products <> coalesce(g.n_products, 0)
