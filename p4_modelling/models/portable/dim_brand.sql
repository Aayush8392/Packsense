{{ config(materialized='table') }}

-- One row per distinct first brand (free text, trimmed and lower-cased). Brands are user-typed, so spelling variants stay separate
-- rows; merging them is a later cleaning step, not a silent guess here. A product with no brand has a NULL brand_key.
select
    {{ dbt.hash('first_brand') }} as brand_key,
    first_brand as brand_name
from (
    select distinct first_brand
    from {{ ref('product_history') }}
    where first_brand is not null
) as brands
