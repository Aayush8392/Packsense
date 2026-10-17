-- The severity columns of dim_flag agree with each other: n_severities is their sum, and every flag has at least one severity.
select flag, n_severities, has_error, has_warning, has_info, has_bug
from {{ ref('dim_flag') }}
where n_severities <> has_error + has_warning + has_info + has_bug
   or n_severities < 1
