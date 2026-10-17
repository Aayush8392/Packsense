{{ config(materialized='table') }}

-- Daily change fact (design section 6.6, P4 slice 5). One row per (UTC day, scope, change group, opened_by_seed):
--   change_date   the UTC day of the opening version's last_modified_t (the edit day, not the day we saw it);
--   scope         'all' = every market; 'india' = periods whose country tags include India (decided on the canonical tag, dim_market);
--   change_group  what changed between a period and the previous one of the same product (macros/change_groups.sql), or
--                 'new_product' (a product's first period when OFF's revision counter says 1 and the version did not come from the seed),
--                 or 'any' (every period after the first, plus every new product).
--   opened_by_seed  1 when the opening version came from the one-time dump. The seed brings products' older versions late, so a day's
--                 count can include late arrivals; the column lets a reader filter or split them out.
-- Only complete days are shown (macro complete_days): OFF delta files run from about 06:30 UTC to 06:30 UTC, so the first and the newest
-- calendar day are partial and are left out until the next capture completes them.
-- Group rows overlap (one edit can change several groups), so group counts are never summed into a total: use the 'any' row.
-- A product's first period has no predecessor, so it is a change of nothing: it appears only as a new product, when that is provable.
-- n_periods counts history periods; n_products counts distinct barcodes; unseen_edits sums the edits OFF's revision counter shows that
-- we never held a version of (a day's counts are therefore a lower bound on real activity).
with base as (
    select
        c.history_key,
        c.code,
        {{ epoch_date('c.valid_from_t') }} as change_date,
        case when c.opened_by_seed then 1 else 0 end as opened_by_seed,
        coalesce(c.unseen_edits, 0) as unseen_edits,
        case when p.history_key is null then 1 else 0 end as is_first,
        case when p.history_key is null and c.rev_at_open = 1 and not c.opened_by_seed then 1 else 0 end as is_new_product,
        {%- for group, cols in change_groups().items() %}
        case when p.history_key is not null and ({% for col in cols %}{{ column_differs(col) }}{{ " or " if not loop.last }}{% endfor %}) then 1 else 0 end as g_{{ group }}{{ "," if not loop.last }}
        {%- endfor %}
    from {{ ref('product_history') }} as c
    left join {{ ref('product_history') }} as p on p.code = c.code and p.valid_to_t = c.valid_from_t
),

india_periods as (
    select distinct m.history_key
    from {{ ref('bridge_product_market') }} as m
    inner join {{ ref('dim_market') }} as d on d.market_code = m.market_code
    where d.is_target_market = 1
),

events as (
    {%- for group in change_groups().keys() %}
    select history_key, code, change_date, opened_by_seed, unseen_edits, '{{ group }}' as change_group from base where g_{{ group }} = 1
    union all
    {%- endfor %}
    select history_key, code, change_date, opened_by_seed, unseen_edits, 'new_product' as change_group from base where is_new_product = 1
    union all
    select history_key, code, change_date, opened_by_seed, unseen_edits, 'any' as change_group from base where is_first = 0 or is_new_product = 1
),

scoped as (
    select e.*, 'all' as scope from events as e
    union all
    select e.*, 'india' as scope from events as e inner join india_periods as i on i.history_key = e.history_key
),

aggregated as (
    select
        change_date,
        scope,
        change_group,
        opened_by_seed,
        count(distinct code) as n_products,
        count(*) as n_periods,
        sum(unseen_edits) as unseen_edits
    from scoped
    cross join {{ complete_days() }} as cd
    where change_date between cd.first_day and cd.last_day
    group by change_date, scope, change_group, opened_by_seed
)

select
    {{ dbt.hash(dbt.concat([dbt.safe_cast('a.change_date', dbt.type_string()), "'|'", 'a.scope', "'|'", 'a.change_group', "'|'", dbt.safe_cast('a.opened_by_seed', dbt.type_string())])) }} as fact_key,
    d.date_key,
    a.change_date,
    a.scope,
    a.change_group,
    a.opened_by_seed,
    a.n_products,
    a.n_periods,
    a.unseen_edits
from aggregated as a
left join {{ ref('dim_date') }} as d on d.calendar_date = a.change_date
