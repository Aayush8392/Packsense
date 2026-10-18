-- The scorecard's coverage counts (scope 'all', all brands added up) recounted straight from product_history on the scorecard's day: the
-- category and label counts here come from the tag ARRAYS, the model takes them from the bridges, so this also ties the two together.
with day as (
    select max(as_of_date) as d from {{ ref('mart_brand_scorecard') }}
),

alive as (
    select h.*
    from {{ ref('product_history') }} as h cross join day as dd
    where {{ epoch_date('h.valid_from_t') }} <= dd.d
      and (h.valid_to_t is null or {{ epoch_date('h.valid_to_t') }} > dd.d)
),

expected as (
    select
        count(*) as n_products,
        sum(case when nutrition_format <> 'none' then 1 else 0 end) as n_with_nutrition,
        sum(case when nutriscore_grade in ('a', 'b', 'c', 'd', 'e') then 1 else 0 end) as n_with_nutriscore,
        sum(case when nova_group is not null then 1 else 0 end) as n_with_nova,
        sum(case when quantity_amount is not null then 1 else 0 end) as n_with_quantity,
        sum(case when ingredients_sha256 is not null then 1 else 0 end) as n_with_ingredients,
        sum(case when {{ distinct_array_size('categories_tags') }} > 0 then 1 else 0 end) as n_with_categories,
        sum(case when {{ distinct_array_size('labels_tags') }} > 0 then 1 else 0 end) as n_with_labels
    from alive
),

got as (
    select
        sum(n_products) as n_products,
        sum(n_with_nutrition) as n_with_nutrition,
        sum(n_with_nutriscore) as n_with_nutriscore,
        sum(n_with_nova) as n_with_nova,
        sum(n_with_quantity) as n_with_quantity,
        sum(n_with_ingredients) as n_with_ingredients,
        sum(n_with_categories) as n_with_categories,
        sum(n_with_labels) as n_with_labels
    from {{ ref('mart_brand_scorecard') }}
    where scope = 'all'
)

select e.*, g.n_products as got_products, g.n_with_nutrition as got_nutrition, g.n_with_nutriscore as got_nutriscore, g.n_with_nova as got_nova,
       g.n_with_quantity as got_quantity, g.n_with_ingredients as got_ingredients, g.n_with_categories as got_categories, g.n_with_labels as got_labels
from expected as e cross join got as g
where e.n_products <> g.n_products or e.n_with_nutrition <> g.n_with_nutrition or e.n_with_nutriscore <> g.n_with_nutriscore
   or e.n_with_nova <> g.n_with_nova or e.n_with_quantity <> g.n_with_quantity or e.n_with_ingredients <> g.n_with_ingredients
   or e.n_with_categories <> g.n_with_categories or e.n_with_labels <> g.n_with_labels
