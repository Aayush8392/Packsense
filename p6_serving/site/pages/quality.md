---
title: Quality over time
---

Open Food Facts runs its own checks on every product and attaches *flags* (errors, warnings, info). This page counts flags that are open on the products we hold, at the end of each complete day. A count is of flags, not of products: one product can carry many. A rise mostly reflects how many products we hold, so read the second chart for change in quality.

<Dropdown name=scope title="Products" defaultValue="all">
  <DropdownOption value="all" valueLabel="All markets" />
  <DropdownOption value="india" valueLabel="India" />
</Dropdown>

```sql by_severity
select
  cast(snapshot_date as date) as day,
  severity,
  sum(open_spans) as open_flags
from site.quality_daily
where scope = '${inputs.scope.value}'
group by 1, 2
order by 1
```

<LineChart data={by_severity} x=day y=open_flags series=severity title="Open flags by severity" />

```sql per_product
select
  cast(snapshot_date as date) as day,
  severity,
  round(sum(open_spans) * 1.0 / max(n_products_held), 2) as flags_per_product
from site.quality_daily
where scope = '${inputs.scope.value}'
group by 1, 2
order by 1
```

<LineChart data={per_product} x=day y=flags_per_product series=severity title="Open flags per product held" />

## Which kinds of flag

```sql families
select
  flag_family,
  severity,
  sum(open_spans) as open_flags
from site.quality_daily
where scope = '${inputs.scope.value}'
  and snapshot_date = (select max(snapshot_date) from site.quality_daily)
group by 1, 2
having sum(open_spans) > 0
order by open_flags desc
limit 20
```

<DataTable data={families} rows=20>
  <Column id=flag_family title="Flag family (check of Open Food Facts)" />
  <Column id=severity title="Severity" />
  <Column id=open_flags title="Open flags" fmt=num0 />
</DataTable>

Counts of 1 to 4 are hidden in the underlying data (small numbers), so a family with only a few flags can be missing or understated here. "Unmapped" flags are ones that Open Food Facts generates in code and that its published taxonomy does not list.

<small>Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/).</small>
