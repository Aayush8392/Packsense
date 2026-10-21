---
title: Daily changes
---

How many products were edited each day, counted from the versions we hold (days our files cover completely). New products are products whose first edit was their creation outside the one-time seed. These are lower bounds: Open Food Facts publishes one row per product per day, and we sometimes miss edits between two versions.

<Dropdown name=scope title="Products" defaultValue="all">
  <DropdownOption value="all" valueLabel="All markets" />
  <DropdownOption value="india" valueLabel="India" />
</Dropdown>

```sql daily
select
  cast(change_date as date) as day,
  change_group,
  sum(n_products) as products
from site.change_daily
where scope = '${inputs.scope.value}' and change_group in ('any', 'new_product')
group by 1, 2
order by 1
```

<LineChart data={daily} x=day y=products series=change_group title="Products edited per day" />

## What kind of edit

```sql groups
select
  change_group,
  sum(n_products) as product_edits
from site.change_daily
where scope = '${inputs.scope.value}' and change_group not in ('any', 'new_product')
group by 1
order by 2 desc
```

<BarChart data={groups} x=change_group y=product_edits swapXY=true title="Edits by group over all complete days (one edit can touch several groups)" />

Counts of 1 to 4 are hidden in the underlying data (small numbers).

<small>Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/).</small>
