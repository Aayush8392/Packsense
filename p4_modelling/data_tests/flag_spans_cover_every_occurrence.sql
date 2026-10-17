-- Nothing lost, nothing counted twice: the versions across all spans equal the distinct (version, flag) occurrences.
select spans.n_in_spans, occ.n_occurrences
from (select sum(versions_present) as n_in_spans from {{ ref('product_flag_spans') }}) as spans
cross join (
    select count(*) as n_occurrences
    from (select distinct code, severity, flag, last_modified_t from {{ ref('stg_flag_occurrences') }}) as d
) as occ
where spans.n_in_spans <> occ.n_occurrences
