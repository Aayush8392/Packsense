-- Volume shape of the daily quality fact: every day it shows must have the same number of (scope, severity, flag family) rows, because the
-- model builds the full grid of days x groups. A day with fewer rows means a dropped day or group that the other tests (which sum what is there) would miss.
with per_day as (
    select snapshot_date, count(*) as n
    from {{ ref('fct_catalogue_quality_daily') }}
    group by snapshot_date
),

widest as (
    select max(n) as n from per_day
)

select p.snapshot_date, p.n as rows_that_day, w.n as rows_expected
from per_day as p cross join widest as w
where p.n <> w.n
