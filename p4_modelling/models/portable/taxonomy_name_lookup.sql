{{ config(materialized='table') }}

-- Which taxonomy tag a written name belongs to, for tags that users entered in the wrong language or case (en:Milch, fr:Avoine, en:Türkiye).
-- One row per (taxonomy, lower-cased trimmed name) across ALL languages of the taxonomy: the language prefix of a product tag is unreliable
-- (en:Milch is German), so it is ignored. n_tags is how many different tags carry that name: when it is not 1 the name is ambiguous and
-- no canonical tag may be chosen from it (`tag` is then only the smallest candidate, kept for inspection).
select
    taxonomy,
    name_key,
    count(distinct tag) as n_tags,
    min(tag) as tag
from (
    select taxonomy, tag, lower(trim(name_text)) as name_key
    from {{ ref('stg_taxonomy_names') }}
    where name_text is not null
) as names
where name_key <> ''
group by taxonomy, name_key
