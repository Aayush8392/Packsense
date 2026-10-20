-- A status must come with the evidence that can give it: a snapshot row says `present_in_snapshot` and only that; every other answer comes from OFF's API;
-- an `unverified` product has no check at all. A row that breaks this means the silver table or the loader wrote something the model does not understand.
select code, status, evidence_source, checked_at
from {{ ref('product_status') }}
where (status = 'present_in_snapshot' and coalesce(evidence_source, '') <> 'snapshot')
   or (status in ('confirmed_exists', 'confirmed_not_found', 'moved_other_type', 'invalid_code', 'unconfirmed') and coalesce(evidence_source, '') <> 'off_api_v2')
   or (status = 'unverified' and (evidence_source is not null or checked_at is not null or detail is not null))
