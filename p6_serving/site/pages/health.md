---
title: Pipeline health
---

```sql status
select
  cast(built_at_utc as timestamp) as built_at,
  cast(last_complete_day as date) as last_day,
  products_held_all,
  date_diff('day', cast(first_complete_day as date), cast(last_complete_day as date)) + 1 as days_covered
from site.site_status
```

<BigValue data={status} value=built_at title="Site data built (UTC)" fmt="yyyy-mm-dd hh:mm" />
<BigValue data={status} value=last_day title="Complete through" fmt=yyyy-mm-dd />
<BigValue data={status} value=days_covered title="Complete days held" fmt=num0 />
<BigValue data={status} value=products_held_all title="Products held" fmt=num0 />

This page shows only what the public data can say. Capture and load times, job durations and service limits arrive with the capacity panel.

## Products held over time

```sql held
select cast(snapshot_date as date) as day, scope, max(n_products_held) as products_held
from site.quality_daily
group by 1, 2
order by 1
```

<LineChart data={held} x=day y=products_held series=scope title="Products held at the end of each complete day" />

The number rises because we hold only products edited since we began capturing (30 September 2026) plus a one-time seed of India products. It is not the size of Open Food Facts.

<small>Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/).</small>
