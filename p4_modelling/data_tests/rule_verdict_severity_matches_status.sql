-- A violated verdict always has a severity; any other status has none and no deviation.
select code, rule, status, severity, deviation
from {{ ref('product_rule_verdicts') }}
where (status = 'violated' and (severity is null or severity not in ('error', 'warning')))
   or (status <> 'violated' and (severity is not null or deviation is not null))
