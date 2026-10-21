---
title: PackSense
---

A daily-updated, cleaned and versioned copy of the Open Food Facts catalogue, with the quality of what it holds measured every day. India first.

```sql status
select
  cast(built_at_utc as timestamp) as built_at,
  cast(first_complete_day as date) as first_day,
  cast(last_complete_day as date) as last_day,
  products_held_all,
  products_held_india
from site.site_status
```

<BigValue data={status} value=products_held_all title="Products held" fmt=num0 />
<BigValue data={status} value=products_held_india title="Of which India" fmt=num0 />
<BigValue data={status} value=last_day title="Data complete through" fmt=yyyy-mm-dd />
<BigValue data={status} value=built_at title="Site data built (UTC)" fmt="yyyy-mm-dd hh:mm" />

**Read this first.** The figures describe *our copy* of Open Food Facts at the time shown above, not Open Food Facts itself. Daily charts stop at the last complete day: the newest day is left out until the next capture completes it. A product can be up to a day behind its live page on Open Food Facts. Open Food Facts is crowd-edited, so these pages say a value is *consistent* or *flagged*, never that it is *correct*.

## What is here

- [Brand scorecard](/brands): how completely the larger brands' products are filled in.
- [Quality over time](/quality): how many quality flags the checks of Open Food Facts have open, and how that moves.
- [Daily changes](/changes): how many products were edited each day, and what kind of edit.
- [Pipeline health](/health): how fresh the data is and how much of it we hold.
- [About this data](/about): sources, licence, method and limits.

<small>Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/).</small>
