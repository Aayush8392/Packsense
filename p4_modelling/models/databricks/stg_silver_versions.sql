{{ config(materialized='view') }}

{% if var('fixture_mode', false) %}
-- Fixture mode (the throwaway verification schema only, target `fixture_admin`): the committed fixture IS this view's output for a
-- chosen real slice, so the portable models can be run on it and compared with DuckDB. Never set in dev or production.
select * from {{ source('fixture', 'fixture_stg_silver_versions') }}
{% else %}
-- Staging over silver. Databricks-only: it is the one place that reads the hashed contributor columns, and only to count
-- distinct editors. Those columns never pass through: the EXCEPT list below is the contract's `egress: never` list
-- (a test in p4_modelling/tests compares the two), and `distinct_editors` is the only value derived from them.
with src as (
    select
        * except (
            creator_hmac, last_editor_hmac, editors_hmac, informers_hmac, correctors_hmac, checkers_hmac,
            photographers_hmac, weighers_hmac, last_checker_hmac, owner_hmac, hmac_key_version
        ),
        coalesce(size(array_distinct(editors_hmac)), 0) as distinct_editors
    from {{ source('silver', 'silver_product_versions') }}
),

parsed as (
    select
        *,
        timestamp_seconds(last_modified_t) as last_modified_ts,
        timestamp_seconds(created_t) as created_ts,
        source_file like 'seed-dump:%' as is_seed,
        cast(nullif(regexp_extract(source_file, '^openfoodfacts_products_([0-9]+)_([0-9]+)[.]json[.]gz$', 1), '') as bigint) as delta_start_t,
        cast(nullif(regexp_extract(source_file, '^openfoodfacts_products_([0-9]+)_([0-9]+)[.]json[.]gz$', 2), '') as bigint) as delta_end_t,
        -- a GTIN-14 form so the 8-, 12- and 13-digit forms of one product line up
        case
            when code_kind in ('gtin8', 'gtin12', 'gtin13', 'gtin14') and code rlike '^[0-9]+$' then lpad(code, 14, '0')
        end as gtin14,
        case when code_kind in ('gtin12', 'gtin13') then left(lpad(code, 13, '0'), 3) end as gs1_prefix,
        -- the brand dimension groups by the first brand of the free-text list, trimmed and lower-cased (about 7% of versions list several)
        nullif(lower(trim(split(brands, ',')[0])), '') as first_brand
    from src
)

select
    *,
    timestamp_seconds(delta_start_t) as delta_window_start,
    timestamp_seconds(delta_end_t) as delta_window_end,
    -- GS1 check digit: weights 3,1,3,... over the first 13 digits of the GTIN-14
    case
        when gtin14 is null then null
        else (10 - (aggregate(
                transform(sequence(1, 13), i -> cast(substr(gtin14, i, 1) as int) * case when i % 2 = 1 then 3 else 1 end),
                0,
                (acc, x) -> acc + x
            ) % 10)) % 10 = cast(substr(gtin14, 14, 1) as int)
    end as code_check_digit_valid,
    {{ tracked_hash() }} as tracked_hash
from parsed
{% endif %}
