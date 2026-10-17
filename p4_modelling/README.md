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

## Gold principals and grants (set by an admin in the SQL editor, kept here so they can be re-created)
Two principals, each with the **Workspace access** and **Databricks SQL access** entitlements, **Can use** on the SQL warehouse and nothing else.
Replace `<principal>` with the application (client) id. A principal reads exactly two silver tables and writes only its own gold schema:
it has no access to bronze, to quarantine, or to the secret scope `packsense`. No `CREATE SCHEMA`: an admin creates the schema first.
Unity Catalog has no `CREATE VIEW` privilege; `CREATE TABLE` covers views.

Prod (`packsense-gold`; schema `workspace.packsense_gold`):
```sql
CREATE SCHEMA IF NOT EXISTS workspace.packsense_gold;
GRANT USE CATALOG ON CATALOG workspace TO `<principal>`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_silver TO `<principal>`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_product_versions TO `<principal>`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_manifest TO `<principal>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_gold TO `<principal>`;
GRANT SELECT ON SCHEMA workspace.packsense_gold TO `<admin user>`;
```
Dev (`packsense-gold-dev`): the same shapes on `workspace.packsense_dev_silver` and `workspace.packsense_dev_gold`.

Table-level grants on silver are lost when a silver table is renamed or dropped and recreated (the table-swap runbook): re-grant afterwards.
A table is owned by the principal that created it and a schema owner gets no read access to it, hence the standing `SELECT` for the admin.

## Run locally (dev)
```
pip install -r p4_modelling/requirements.txt
dbt parse --project-dir p4_modelling --profiles-dir p4_modelling
```
A real run needs `DATABRICKS_HOST`, `DBT_HTTP_PATH` and either `DATABRICKS_TOKEN` (target `dev_admin`) or the gold-dev client id and secret (target `dev`).
