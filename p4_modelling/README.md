# P4 Modelling: the gold layer (dbt Core)

Status: **first slice built and scheduled, 2026-10-17.** The gold job runs on dev and on production (daily 09:30 UTC, after the bronze job).
The module's exit gate, the DuckDB comparison on a real fixture, is not done yet.

Gold is built from silver only, by its own job and its own principals (`packsense-gold-dev`, `packsense-gold`), so the single-writer rule
holds: the bronze principal never writes gold, and gold never reads bronze, quarantine or the secret scope `packsense`.

## What exists
- **Project:** `dbt_project.yml`, `profiles.yml` (no secrets: host, warehouse path and credentials come from the environment), `requirements.txt` (pinned dbt).
  dbt lives in its own virtual environment (`.venv-dbt`): installing it next to the Databricks SDK in the main one downgrades the SDK.
- **Databricks-only staging** (`models/databricks/`): `stg_silver_versions` (drops the 11 `egress: never` columns, keeps a count of distinct editors in
  their place, adds timestamps, the delta file's window, a GTIN-14 form, the GS1 prefix, a check-digit flag, the first brand and `tracked_hash`),
  `stg_flag_occurrences` and `stg_history_markets` (array explodes).
- **Portable models** (`models/portable/`, plain ANSI SQL so they can run on DuckDB): `product_history` (SCD2 derived from silver's own versions, rebuilt in
  full every run: a period opens when the tracked set changes, versions that change nothing are merged, the open row is `is_latest_observed`),
  `product_flag_spans` (OFF's quality flags as spans, with `first_seen_is_first_version` and `vanished_with_tracked_change`), `product_status` (every
  product `unverified`, insert-only), `dim_brand`, `dim_market` with `bridge_product_market`, and `dim_date`.
- **The tracked set** is one macro (`macros/tracked.sql`): tag arrays are sorted and the nutrients map is hashed by sorted entries, so a pure reordering is not a change.
- **Tests:** 42 dbt tests (no duplicate periods, one open row per code, contiguous periods, versions merged equal silver rows, neighbouring periods differ,
  spans cover every occurrence, no overlap, bridge and dimension coverage) and Python tests that tie the staging view and the tracked set to the silver
  contract (run by CI with the other tests).
- **The job:** a separate bundle (`databricks.yml`, `resources/gold_job.yml`): one serverless notebook (`notebooks/gold_run.py`) runs `dbt build` as the
  gold principal with its OAuth credential read from its own scope (`packsense_gold_dev`, `packsense_gold`). Healthchecks check `packsense-gold` (prod). The run
  time is one variable, `gold_cron`. `bootstrap/gold_scope.py` creates a gold scope and stores its secrets from a hidden prompt.

## Measured on production (2026-10-17, 128,596 silver versions, 118,857 products)
124,284 history periods: 5,427 real changes and 4,312 no-op versions merged (44% of the 9,739 repeat versions; an unsorted comparison of the nutrients map
counts 3,919 of them as changes). 8,443 unseen edits (OFF's `rev` jumps between our versions). 1.09 million flag spans, of which 3,711 vanished, 98.8% of
them together with a tracked change. 99.7% of spans (98.3% of the error spans) were never seen without the flag, so their first appearance is unknown;
only 3,351 spans have a known first appearance.

## Still to do
The DuckDB fixture and comparison (the exit gate) with slim CI, a deploy workflow for gold (today the principals deploy it by hand), the taxonomy loader
and the category, allergen and label dimensions, the change and quality facts and the P4 marts, a rerun-idempotence test, and a weekday column for `dim_date`.

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
python -m venv .venv-dbt
.venv-dbt/Scripts/python -m pip install -r p4_modelling/requirements.txt
dbt parse --project-dir p4_modelling --profiles-dir p4_modelling
```
A real run needs `DATABRICKS_HOST`, `DBT_HTTP_PATH` and either `DATABRICKS_TOKEN` (target `dev_admin`) or the gold-dev client id and secret (target `dev`);
production runs through the job as `packsense-gold`. Deploy: from `p4_modelling`, `databricks bundle validate|deploy|run gold_build -t dev|prod` as the matching principal.
`dbt parse` works offline with dummy environment variables; `dbt compile` and `run` need a real warehouse.
