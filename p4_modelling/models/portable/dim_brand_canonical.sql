{{ config(materialized='table') }}

-- Canonical brand (roadmap Phase D item 21, decided 2026-11-04 after external review 14): one row per raw first brand of dim_brand, mapped to the canonical
-- spelling of its group. Two strings are one brand ONLY when their comparison keys are equal (macros brand_name_key and brand_name_stem_key): accents folded,
-- '&' read as 'and', punctuation and spacing removed, a leading 'the' and trailing legal words dropped, then one trailing 's' dropped from a key of 7 or more
-- characters. NO similarity rule: the fuzzy R3 rule of the measurement (759 merges, 556 of them more than plural or punctuation differences) is not applied,
-- because a wrong merge fuses two brands' counts silently and a missed merge is repaired later with one mapping row. Because groups are equal keys, two groups
-- that both carry real counts can never be chained together by similarity (the colombia / colombina case of the review).
--   canonical_name   the most frequent raw spelling of the group (ties: the shorter, then the later in code-point order), counted over products at their latest observed
--                    period; a string with no letters or digits in a-z, 0-9 (for example a Cyrillic name) has no key and stays itself.
--   merge_rule       'same'   the raw string is its own canonical;  'key'  it differs from the canonical only by case, accents, punctuation, spacing, a leading 'the' or a legal word;
--                    'plural' it also differs by a trailing 's' (trader joe's / trader joes / traderjoes).
-- Nothing reads this table yet: the scorecard still groups by the raw first brand. A consumer (the scorecard, the India release) adopts it in its own change.
with counts as (
    select first_brand, count(*) as n_products
    from {{ ref('product_history') }}
    where is_latest_observed = 1 and first_brand is not null
    group by first_brand
),

base as (
    select b.brand_name as raw, coalesce(c.n_products, 0) as n_products, {{ brand_name_key('b.brand_name') }} as key1
    from {{ ref('dim_brand') }} as b
    left join counts as c on c.first_brand = b.brand_name
),

keyed as (
    select
        raw,
        n_products,
        case when key1 = '' then raw else key1 end as key_r2,
        case when key1 = '' then raw else {{ brand_name_stem_key('key1') }} end as group_key
    from base
),

ranked as (
    select
        *,
        row_number() over (partition by group_key order by n_products desc, length(raw) asc, raw desc) as rn
    from keyed
),

canon as (
    select group_key, raw as canonical_name, key_r2 as canonical_key_r2 from ranked where rn = 1
)

select
    {{ dbt.hash('k.raw') }} as brand_key,
    k.raw as brand_name,
    {{ dbt.hash('c.canonical_name') }} as canonical_brand_key,
    c.canonical_name,
    case
        when k.raw = c.canonical_name then 'same'
        when k.key_r2 = c.canonical_key_r2 then 'key'
        else 'plural'
    end as merge_rule,
    k.n_products
from keyed as k
inner join canon as c on c.group_key = k.group_key
