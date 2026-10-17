{{ config(materialized='table') }}

-- Daily snapshot of OFF's quality flags over the products we HOLD (P4 slice 6, decided 2026-10-18). One row per (UTC day, scope, severity, flag_family):
--   open_spans              flag spans open at the end of the day (a product with two flags in a family counts twice: spans, not products);
--   opened_on_known_product spans that opened that day on a product we had already seen without the flag (a real appearance);
--   carried_in              spans that opened that day on a product's first observed version (the product arrived already flagged: not an
--                           appearance; 99.7% of spans overall);
--   vanished / vanished_with_tracked_change   spans that ended that day, and those where the same version also changed the tracked set;
--   n_products_held         products whose first observed version is on or before the day (the denominator; per scope, repeated on each row).
-- scope 'all' = every product we hold; 'india' = a product that ever had India in a period (a fixed attribute, not as-of). This is the quality of
-- what we hold, not of OFF: non-India markets arrive only as products edited since the capture began (dim_market.coverage).
-- flag_family comes from dim_flag (taxonomy family; the flag itself for a root flag; 'unmapped' when OFF generates the flag in code).
-- The first day shown starts from the stock carried in by the seed and older versions: read the first day's open_spans as that stock, not activity.
-- Days run from the first delta day to the last observed day. Computed as running sums of daily flows (portable ANSI SQL, no day-by-span join).
-- Families come from the newest taxonomy snapshot for every day, so a taxonomy rename relabels old days at the next rebuild.
with flagged as (
    select
        s.code,
        s.severity,
        case f.family_source when 'taxonomy' then f.family when 'root' then s.flag else 'unmapped' end as flag_family,
        {{ epoch_date('s.first_seen_t') }} as opened_date,
        s.first_seen_is_first_version,
        {{ epoch_date('s.vanished_at_t') }} as vanished_date,
        s.vanished_with_tracked_change
    from {{ ref('product_flag_spans') }} as s
    inner join {{ ref('dim_flag') }} as f on f.flag = s.flag
),

india_codes as (
    select distinct m.code
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

scoped as (
    select 'all' as scope, f.* from flagged as f
    union all
    select 'india' as scope, f.* from flagged as f inner join india_codes as i on i.code = f.code
),

bounds as (
    select
        min(case when not opened_by_seed then {{ epoch_date('valid_from_t') }} end) as first_day,
        max({{ epoch_date('valid_from_t') }}) as last_day
    from {{ ref('product_history') }}
),

spine as (
    select d.calendar_date as snapshot_date
    from {{ ref('dim_date') }} as d
    cross join bounds as b
    where d.calendar_date between b.first_day and b.last_day
),

dims as (
    select distinct scope, severity, flag_family from scoped
),

opened as (
    select
        scope, severity, flag_family, opened_date as event_date,
        sum(case when first_seen_is_first_version = 0 then 1 else 0 end) as opened_on_known_product,
        sum(case when first_seen_is_first_version = 1 then 1 else 0 end) as carried_in
    from scoped
    group by scope, severity, flag_family, opened_date
),

vanished as (
    select
        scope, severity, flag_family, vanished_date as event_date,
        count(*) as vanished,
        sum(case when vanished_with_tracked_change = 1 then 1 else 0 end) as vanished_with_tracked_change
    from scoped
    where vanished_date is not null
    group by scope, severity, flag_family, vanished_date
),

stock_before as (
    select scope, severity, flag_family, sum(n) as open_before
    from (
        select o.scope, o.severity, o.flag_family, o.opened_on_known_product + o.carried_in as n
        from opened as o cross join bounds as b where o.event_date < b.first_day
        union all
        select v.scope, v.severity, v.flag_family, -v.vanished as n
        from vanished as v cross join bounds as b where v.event_date < b.first_day
    ) as x
    group by scope, severity, flag_family
),

grid as (
    select
        s.snapshot_date, k.scope, k.severity, k.flag_family,
        coalesce(o.opened_on_known_product, 0) as opened_on_known_product,
        coalesce(o.carried_in, 0) as carried_in,
        coalesce(v.vanished, 0) as vanished,
        coalesce(v.vanished_with_tracked_change, 0) as vanished_with_tracked_change
    from spine as s
    cross join dims as k
    left join opened as o on o.event_date = s.snapshot_date and o.scope = k.scope and o.severity = k.severity and o.flag_family = k.flag_family
    left join vanished as v on v.event_date = s.snapshot_date and v.scope = k.scope and v.severity = k.severity and v.flag_family = k.flag_family
),

first_seen as (
    select code, min({{ epoch_date('valid_from_t') }}) as first_day_seen
    from {{ ref('product_history') }}
    group by code
),

held_flows as (
    select 'all' as scope, first_day_seen, code from first_seen
    union all
    select 'india' as scope, f.first_day_seen, f.code from first_seen as f inner join india_codes as i on i.code = f.code
),

held_daily as (
    select scope, first_day_seen as event_date, count(*) as n from held_flows group by scope, first_day_seen
),

held as (
    select s.snapshot_date, sc.scope, coalesce(sum(h.n), 0) as n_products_held
    from spine as s
    cross join (select distinct scope from dims) as sc
    left join held_daily as h on h.scope = sc.scope and h.event_date <= s.snapshot_date
    group by s.snapshot_date, sc.scope
)

select
    {{ dbt.hash(dbt.concat([dbt.safe_cast('g.snapshot_date', dbt.type_string()), "'|'", 'g.scope', "'|'", 'g.severity', "'|'", 'g.flag_family'])) }} as fact_key,
    d.date_key,
    g.snapshot_date,
    g.scope,
    g.severity,
    g.flag_family,
    coalesce(b.open_before, 0)
        + sum(g.opened_on_known_product + g.carried_in - g.vanished)
            over (partition by g.scope, g.severity, g.flag_family order by g.snapshot_date rows between unbounded preceding and current row) as open_spans,
    g.opened_on_known_product,
    g.carried_in,
    g.vanished,
    g.vanished_with_tracked_change,
    h.n_products_held
from grid as g
left join stock_before as b on b.scope = g.scope and b.severity = g.severity and b.flag_family = g.flag_family
left join held as h on h.snapshot_date = g.snapshot_date and h.scope = g.scope
left join {{ ref('dim_date') }} as d on d.calendar_date = g.snapshot_date
