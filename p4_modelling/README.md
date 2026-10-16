# P4 Modelling: the gold layer (dbt Core)

Status: **started 2026-10-17, dev only.** Nothing here runs in production yet.

Gold is built from silver only, by its own job and its own principal (`packsense-gold-dev` now, `packsense-gold` later), so the
single-writer rule holds: the bronze principal never writes gold and gold never reads bronze, quarantine or the secret scope `packsense`.

## What exists
- `dbt_project.yml`, `profiles.yml` (no secrets: host, warehouse path and credentials come from the environment), `requirements.txt` (pinned dbt).
- `models/databricks/sources.yml`: the two silver tables gold reads.
- `models/databricks/stg_silver_versions.sql`: the staging view over silver. It drops the 11 `egress: never` columns, keeps a count of
  distinct editors in their place, and adds the edit and creation time as timestamps, the seed flag, the delta file's time window, a GTIN-14
  form, the GS1 prefix and a check-digit flag.
- `tests/test_staging_egress.py`: the view's EXCEPT list must equal the contract's `egress: never` set (run by CI with the other tests).

## Still to do (first slice)
History table (SCD2 from silver's own versions, tracked set, no-op versions collapsed, deterministic keys), flag spans, `product_status`
(every product `unverified`), brand, market and date dimensions, tests, the DuckDB comparison on a real fixture, the gold principals and job.
The design is in the private build log; the decisions are summarised in the top-level README when gold is live.

## Run locally (dev)
```
pip install -r p4_modelling/requirements.txt
dbt parse --project-dir p4_modelling --profiles-dir p4_modelling
```
A real run needs `DATABRICKS_HOST`, `DBT_HTTP_PATH` and either `DATABRICKS_TOKEN` (target `dev_admin`) or the gold-dev client id and secret (target `dev`).
