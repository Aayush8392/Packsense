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
| `policies.yml` | step 4: the single source of truth for row filters, column masks and who sees what (see "Row filters and masks" below) |
| `policies_lib.py`, `policies_live.py` | pure logic (validate, SQL, parse what Unity Catalog reports, the plan) and the Databricks side |
| `bootstrap/apply_policies.py` | `plan`, `apply --only dev\|prod\|all`, `check` (exit 1 on any difference) |
| `classification.yml`, `classification_lib.py` | step 5: the mapping from the silver contract's `class` to public / personal / internal, the other tables by hand, gold's default and overrides; the library reads every real column list and renders the document |
| `gold_columns.json`, `bootstrap/gold_columns.py` | the real columns of the 20 portable gold models, dumped from the DuckDB build; the `engines` CI job checks it against a fresh build |
| `bootstrap/render_classification.py` | writes `DATA_CLASSIFICATION.md` (repo root); `--check` fails when it is stale or unsound |
| `tests/test_classification.py` | every silver column classified, hashed columns personal AND masked (ties to `policies.yml`), gold has no personal column, the document is current, a planted mistake is found |
| `tests/test_deny_checks.py` | step 7: every deny check goes red when its action is allowed, passes only on a permission error, and every check really attempts the action on the object it names (a fake identity that may do everything, and one that may do nothing; a no-op attempt fails the test) |
| `tests/test_policies.py` | the file validates, every hashed column of `silver.yml` is masked, the filter tables equal the dbt models that re-apply the filter, the plan drops before it sets, the `rows_only` judgement |
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
- Gold principals read exactly four silver tables (`silver_product_versions`, `silver_manifest`, `silver_taxonomy_tag`, `silver_existence_check`) and write only their own gold
  schema; they have nothing on bronze, quarantine or the secret scope `packsense` (tests check this in the file).
- No principal has `CREATE SCHEMA`: an admin creates schemas and volumes first.
- A table is owned by the principal that created it, and a schema owner gets no read access to it, hence the admin's standing `SELECT` on every pipeline schema.
- Table-level grants are lost when a table is renamed or dropped (the silver table-swap runbook): run `apply` afterwards.
- A secret scope has no per-key permission: `READ` covers every secret in it.

## Policy tests (step 3): what each identity can and cannot do, proven nightly
`policy/checks.yml` lists, per identity, things it must be **denied** and things it must be **allowed**. Each check signs in AS that identity and
tries the action. A deny check passes only on a permission error (a missing table or a timeout is an ERROR, never a pass: a test that is denied
for the wrong reason proves nothing); an allow check passes only on success. `tests/test_policy.py` ties the checks to `grants.yml` in both
directions, so the two files cannot drift apart.

| Piece | What it does |
|---|---|
| four jobs `packsense-policy-<principal>` | each runs AS one service principal (`run_as`), so no principal secret is stored anywhere; the notebook refuses to run if the job's identity is not the one it was told to test |
| job `packsense-policy` (admin-owned) | nightly at 03:00 UTC: starts the four jobs, tests the pipeline user and the analyst with their own tokens (scope `packsense_policy`), runs the grants drift check, then reports once to the healthchecks check `packsense-policy` |
| `policy/notebooks/grants_drift.py` | the same comparison as `apply_grants.py check`; any missing or extra grant, or a role whose token no longer works, turns it red |
| `bootstrap/policy_scope.py` | creates the scope and stores the two user tokens and the ping URL (hidden prompts) |

The bundle is deployed by the **admin from the laptop** (there is no Databricks admin credential in CI, by decision): the admin must hold
the Use permission on the four service principals, and `bundle deploy` / `bundle run` use the admin token. The schedule (variable
`policy_cron`, 03:00 UTC) is UNPAUSED and the report pings healthchecks (variable `ping`), after every job passed once by hand and
a deliberate violation turned the run red (2026-10-19: a forbidden `SELECT` on dev bronze for `packsense-gold-dev` and on prod gold for the
analyst made three tasks fail: the gold-dev job, the analyst test and the drift check; revoking them made the next run green). To repeat
the proof, plant a forbidden grant (or a forbidden action in `checks.yml`), run `bundle run policy`, and revoke it again.

## Row filters and masks (step 4)
`policies.yml` lists who sees which market (`access`), which gold tables carry a row filter on the raw market tag (`bridge_product_market`,
`dim_market`) and the ten hashed contributor columns of `silver_product_versions`, which are masked. Everything hangs on one small table,
`workspace.packsense_policy.market_access` (principal, market): a row `*` means "everything, and hashed columns unmasked", a row for a market
lets that principal see that market, a principal with no row sees nothing (it fails closed). Three functions read it: `market_filter`,
`mask_string`, `mask_array`. Exempt (`*`): the admin, both deployers, both gold principals. The analyst sees `en:india` only (the raw tag, so a
variant spelling of India is a different value and is not shown).

**What was measured (2026-10-19, dev) and shaped the design**
- A filter with a mapping-table lookup works for the analyst, who needs no right on the mapping table; the function exempts by identity.
- `CREATE OR REPLACE TABLE` run by the admin kept the filter, but **a real dbt build as the owning principal dropped it** (grants stayed): the
  analyst then read every market (92,224 rows, 231 markets instead of 2,538 rows, 1 market). So gold re-applies the filter right after each
  model builds (dbt post-hook, macro `apply_market_filter`; the gold principals hold `USE_SCHEMA` and `EXECUTE` on the policy schema), and the
  nightly job proves what the analyst really sees (`rows_only` checks) and compares the attached filters and masks with this file
  (`policies_drift.py`).
- A drop and recreate loses grants and the filter; a rename keeps a mask on the renamed (old) table, so a freshly created table after a swap
  has none: run `apply_policies.py apply` after a table swap.
- Setting a filter or mask on a table that already has one fails for the admin ('MODIFY'); dropping first works, so `apply` drops a different
  one and sets the right one, and leaves a matching one alone (idempotent).
- A dbt run as `packsense-gold-dev` on masked dev silver succeeded (166 nodes) and `distinct_editors` was still computed: the exempt principals
  read the hashed columns.

**Limits, stated plainly.** Between a table being replaced and the post-hook running (seconds) the analyst could read an unfiltered table; the
nightly check catches anything longer. A mask has no non-exempt reader to test it with (nobody but the exempt principals holds `SELECT` on
silver), so it is checked by metadata (it is attached), not by behaviour. Whether a MERGE into masked silver by the deployer works is proven
for the admin on scratch and for the gold read on dev; the first scheduled silver write after the production mask is the real test. Prod is
applied by name (`--only prod`): a mask on production silver is a production change.

## Documents (step 7)
`SECURITY.md` (reporting policy and the controls that exist against those only designed) and `THREAT_MODEL.md` (secret leak, a compromised dependency or build step, prompt injection through product text) sit at the repo root. They are public, so they name no secret, date or identifier, and they mark every control as built (exercised) or designed (not built). Known gaps are listed, not hidden: no hash locking of Python dependencies and no committed Terraform provider lock file.

## Data classification (step 5)
`DATA_CLASSIFICATION.md` (repo root) labels every column **public**, **personal** or **internal**. It is generated, never edited: silver's 81
columns come from the `class` column of `silver.yml` (hashed to personal, lineage to internal, a never-leaves column that is not hashed to
internal, the rest public), the other tables (bronze, quarantine, bookkeeping, taxonomy, the access table) are listed in `classification.yml`
with a reason, and gold's 213 columns are public unless overridden. To change a class, edit `classification.yml` or `silver.yml` and run
`python p5_governance/bootstrap/render_classification.py`. After a gold model gains or loses a column, rebuild the DuckDB fixture, run
`bootstrap/gold_columns.py dump --duckdb p4_modelling/target/fixture.duckdb` and render again (the `engines` job fails until you do).
The classification is a label and a policy, not a guarantee: the document says so, and the privacy audit (step 6) carries the measured numbers.

## Privacy audit and licence gate (step 6)
**`PRIVACY_AUDIT.md`** (repo root) reports how much personal-looking text is left in what the pipeline keeps, as bounds measured on all rows and dated. It is
generated from `privacy_audit.json`, which `bootstrap/privacy_audit.py` measures on production (admin, read-only, six SQL statements, **counts only**: the
raw contributor names are read and joined inside Databricks and only integers leave). To refresh it: run the script, then `bootstrap/render_privacy_audit.py`.
First run 2026-10-19 on 147,243 bronze rows: after the scrub no contact-shaped text is left in `product_name` or `brands` (the raw records had it in 9 names and 2 brands);
at most 128 silver names and 128 brands contain a known contributor name of 8+ characters outside ordinary words (the pipeline's own-handle redaction only
touches the record's own contributors, and `brands` is exempt by design); 8 names and 1 brand have a 10-digit Indian-mobile shape (phone numbers are not scrubbed by pattern).
Tests keep the document current, the stored result to integers, and the measured result consistent with the pipeline's promise (a pattern hit in silver would be a defect).

**`licence_gate.py`** checks the RENDERED output of an export (a release folder with `release_manifest.json`): the manifest names the source, a source dump date, the licence
ODbL-1.0 and an attribution that says Open Food Facts and the Open Database License and links both; the export went through the exit function with a passed residue scan;
no product images (no image column, URL or data); a score file holds only barcode, score and provenance; a data file holds no column that the classification marks personal or
internal; a page carries the attribution; listed files exist and match their sha256; and the rendered text is re-scanned for the scrub patterns (a hit is reported as a count, never
as the value). `bootstrap/check_release.py <folder>` runs it by hand. The wording follows Open Food Facts' terms and data pages (read 2026-10-19: ODbL for the database, DbCL for
its contents, CC BY-SA for images with other rights possibly attached; attribute Open Food Facts with a link and link the ODbL). **It is not wired into a real export yet**:
none exists until P6, which must call `check_release()` as the last step before publishing and fail on any violation. The tests use real fixture rows and break one rule at a time.

## The grants (generated from `grants.yml`: do not edit by hand)
<!-- grants:begin -->
```sql
GRANT USE CATALOG ON CATALOG workspace TO `admin`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-deployer`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-deployer-dev`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-gold`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-gold-dev`;
GRANT USE CATALOG ON CATALOG workspace TO `packsense-publish`;
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
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_snapshots TO `packsense-deployer`;
GRANT SELECT ON SCHEMA workspace.packsense_snapshots TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_dev_snapshots TO `packsense-deployer-dev`;
GRANT SELECT ON SCHEMA workspace.packsense_dev_snapshots TO `admin`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_gold TO `packsense-gold`;
GRANT SELECT ON SCHEMA workspace.packsense_gold TO `admin`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_gold TO `analyst`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_gold TO `packsense-publish`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_dev_gold TO `packsense-gold-dev`;
GRANT SELECT ON SCHEMA workspace.packsense_dev_gold TO `admin`;
GRANT USE SCHEMA, EXECUTE ON SCHEMA workspace.packsense_policy TO `packsense-gold`;
GRANT USE SCHEMA, EXECUTE ON SCHEMA workspace.packsense_policy TO `packsense-gold-dev`;
GRANT SELECT ON TABLE workspace.packsense_gold.bridge_product_market TO `analyst`;
GRANT SELECT ON TABLE workspace.packsense_gold.dim_market TO `analyst`;
GRANT SELECT ON TABLE workspace.packsense_gold.mart_brand_scorecard TO `packsense-publish`;
GRANT SELECT ON TABLE workspace.packsense_gold.fct_catalogue_quality_daily TO `packsense-publish`;
GRANT SELECT ON TABLE workspace.packsense_gold.fct_product_change_daily TO `packsense-publish`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_health TO `packsense-publish`;
GRANT SELECT ON TABLE workspace.packsense_health.health_metric_daily TO `packsense-publish`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_product_versions TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_manifest TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_taxonomy_tag TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_product_versions TO `packsense-gold-dev`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_manifest TO `packsense-gold-dev`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_taxonomy_tag TO `packsense-gold-dev`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_existence_check TO `packsense-gold`;
GRANT SELECT ON TABLE workspace.packsense_dev_silver.silver_existence_check TO `packsense-gold-dev`;
-- secret scope packsense: READ for `packsense-deployer`
-- secret scope packsense: MANAGE for `admin`
-- secret scope packsense_dev: READ for `packsense-deployer-dev`
-- secret scope packsense_dev: MANAGE for `admin`
-- secret scope packsense_gold: READ for `packsense-gold`
-- secret scope packsense_gold: MANAGE for `admin`
-- secret scope packsense_gold_dev: READ for `packsense-gold-dev`
-- secret scope packsense_gold_dev: MANAGE for `admin`
-- secret scope packsense_publish: READ for `packsense-publish`
-- secret scope packsense_publish: MANAGE for `admin`
-- secret scope packsense_health: MANAGE for `admin`
-- secret scope packsense_release: MANAGE for `admin`
-- secret scope packsense_policy: MANAGE for `admin`
```
<!-- grants:end -->
