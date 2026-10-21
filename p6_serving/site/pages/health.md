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

## The scheduled jobs

```sql jobs
with newest as (select max(cast(metric_date as date)) as d from site.pipeline_health)
select
  subject as job,
  round(max(case when metric = 'hours_since_last_success' and cast(metric_date as date) = (select d from newest) then cast(value as double) end), 1) as hours_since_success,
  sum(case when metric = 'runs' then cast(value as double) end) as runs,
  sum(case when metric = 'failed_runs' then cast(value as double) end) as failed_runs,
  round(max(case when metric = 'max_duration_seconds' then cast(value as double) end) / 60.0, 1) as longest_run_minutes
from site.pipeline_health
where subject like 'packsense-%' and cast(metric_date as date) >= (select d from newest) - 6
group by 1
order by 1
```

<DataTable data={jobs} rows=15>
  <Column id=job title="Job" />
  <Column id=hours_since_success title="Hours since last success" fmt=num1 />
  <Column id=runs title="Runs, last 7 days" fmt=num0 />
  <Column id=failed_runs title="Not successful" fmt=num0 />
  <Column id=longest_run_minutes title="Longest run (minutes)" fmt=num1 />
</DataTable>

Every job runs on Databricks' scheduler. A run that did not succeed is counted here whatever the reason: a failed check that was set up to fail on purpose, a manual test run and a real fault all look the same. A job that has not succeeded for longer than its schedule shows a large number in the second column. Day boundaries are UTC.

```sql durations
select cast(metric_date as date) as day, subject as job, max(cast(value as double)) / 60.0 as minutes
from site.pipeline_health
where metric = 'max_duration_seconds'
  and subject in ('packsense-bronze-load', 'packsense-gold-build', 'packsense-publish', 'packsense-archive')
group by 1, 2
order by 1
```

<LineChart data={durations} x=day y=minutes series=job title="Longest run per day (minutes), the four daily data jobs" />

## The outside services we depend on

```sql services
with newest as (select max(cast(metric_date as date)) as d from site.pipeline_health)
select
  subject as service,
  max(case when metric = 'reachable' then cast(value as double) end) as reachable,
  max(case when metric = 'reachable' then detail end) as answer,
  round(max(case when metric = 'response_seconds' then cast(value as double) end), 2) as response_seconds
from site.pipeline_health
where metric in ('reachable', 'response_seconds') and cast(metric_date as date) = (select d from newest)
group by 1
order by 1
```

<DataTable data={services} rows=10>
  <Column id=service title="Service (what we use it for)" />
  <Column id=reachable title="Answered (1 = yes)" fmt=num0 />
  <Column id=answer title="Answer" />
  <Column id=response_seconds title="Seconds" fmt=num2 />
</DataTable>

One light request to each service a day, from the same kind of machine the real jobs run on. An answer of HTTP 403 from the storage endpoint is expected: it means the endpoint is reachable and we sent no credentials. This is a daily check, so it can miss an outage that starts and ends between two checks.

```sql down
select cast(metric_date as date) as day, count(*) - sum(cast(value as double)) as services_not_answering
from site.pipeline_health
where metric = 'reachable'
group by 1
order by 1
```

<BarChart data={down} x=day y=services_not_answering title="Services that did not answer, per day" />

## What this page does not show

It shows no storage size and no cost or quota figure. Databricks' storage metrics table is empty on the free plan, and we keep spending and quota numbers off this public site. The job history starts on 19 October 2026, when the first record was written.


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
