# P5 Governance: who may do what

Step 2 of P5 (grants as code). One file, `grants.yml`, says what every principal may do in Unity Catalog and in the Databricks secret
scopes. A script compares it with the live state and adds what is missing. There is no Databricks admin credential in CI: an admin
runs the script, and the nightly policy-test job (step 3) will run the same comparison to catch drift.

## Files
| File | What it does |
|---|---|
| `grants.yml` | the source of truth: roles, securables with their privileges per role, secret-scope ACLs |
| `grants_lib.py` | pure logic: load and validate the file, the set of grants it expects, the diff, the SQL block below |
| `grants_live.py` | the Databricks side: resolve principals, read live grants, add what is missing (never revokes) |
| `bootstrap/apply_grants.py` | `plan` (show the difference), `apply` (add the missing), `check` (exit 1 on any difference) |
| `bootstrap/render_readme_block.py` | rewrites the block below from `grants.yml` |
| `tests/test_grants.py` | the file validates, a planted missing and a planted extra grant are both found, no other README keeps a copy, every schema and scope the bundles name is covered, this block is current |

## Running it (an admin, from the repo root)
```
python p5_governance/bootstrap/apply_grants.py plan  --env-file .env
python p5_governance/bootstrap/apply_grants.py apply --env-file .env
python p5_governance/bootstrap/apply_grants.py check --env-file .env
```
`apply` only adds. A grant that exists live and is not in the file is reported as **EXTRA** and left alone: revoking is the destructive
direction, so a human decides. Principals are named by role in the file; the script resolves a service principal by its display name and
a user from the owner of the token in `.env` (`DATABRICKS_TOKEN` is the admin; `DATABRICKS_PIPELINE_TOKEN` and `DATABRICKS_ANALYST_TOKEN`
are optional: a role without a working token is skipped and said so, and that user's live grants then show up as extra).

## Rules this file encodes
- Both deployers and both gold principals have the **Workspace access** entitlement and nothing else (the gold ones also **Databricks SQL
  access** and **Can use** on the SQL warehouse). Those entitlements are not grants; they are set in the workspace and are not checked here.
- Gold principals read exactly three silver tables (`silver_product_versions`, `silver_manifest`, `silver_taxonomy_tag`) and write only their own gold
  schema; they have nothing on bronze, quarantine or the secret scope `packsense` (tests check this in the file).
- No principal has `CREATE SCHEMA`: an admin creates schemas and volumes first.
- A table is owned by the principal that created it, and a schema owner gets no read access to it, hence the admin's standing `SELECT` on every pipeline schema.
- Table-level grants are lost when a table is renamed or dropped (the silver table-swap runbook): run `apply` afterwards.
- A secret scope has no per-key permission: `READ` covers every secret in it.

## The grants (generated from `grants.yml`: do not edit by hand)
<!-- grants:begin -->
```sql
GRANT USE CATALOG ON CATALOG workspace TO `packsense-deployer`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-deployer-dev`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-gold`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-gold-dev`;
GRANT USE CATALOG ON CATALOG workspace TO `pipeline-user`;
GRANT USE CATALOG ON CATALOG workspace TO `analyst`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense TO `packsense-deployer`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense TO `pipeline-user`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME workspace.packsense.landing TO `packsense-deployer`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME workspace.packsense.landing TO `pipeline-user`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_dev TO `packsense-deployer-dev`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME workspace.packsense_dev.landing TO `packsense-deployer-dev`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_bronze TO `packsense-deployer`;
GRANT SELECT ON SCHEMA workspace.packsense_bronze TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_silver TO `packsense-deployer`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_silver TO `packsense-gold`;
GRANT SELECT ON SCHEMA workspace.packsense_silver TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_dev_bronze TO `packsense-deployer-dev`;
GRANT SELECT ON SCHEMA workspace.packsense_dev_bronze TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_dev_silver TO `packsense-deployer-dev`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_dev_silver TO `packsense-gold-dev`;
GRANT SELECT ON SCHEMA workspace.packsense_dev_silver TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_gold TO `packsense-gold`;
GRANT SELECT ON SCHEMA workspace.packsense_gold TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_dev_gold TO `packsense-gold-dev`;
GRANT SELECT ON SCHEMA workspace.packsense_dev_gold TO `admin`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_product_versions TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_manifest TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_taxonomy_tag TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_product_versions TO `packsense-gold-dev`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_manifest TO `packsense-gold-dev`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_taxonomy_tag TO `packsense-gold-dev`;
-- secret scope packsense: READ for `packsense-deployer`
-- secret scope packsense: MANAGE for `admin`
-- secret scope packsense_dev: READ for `packsense-deployer-dev`
-- secret scope packsense_dev: MANAGE for `admin`
-- secret scope packsense_gold: READ for `packsense-gold`
-- secret scope packsense_gold: MANAGE for `admin`
-- secret scope packsense_gold_dev: READ for `packsense-gold-dev`
-- secret scope packsense_gold_dev: MANAGE for `admin`
```
<!-- grants:end -->
