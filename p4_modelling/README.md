# P4 Modelling: the gold layer (dbt Core)

Status (2026-10-17): **the exit gate is met and about half of the planned models are built.** The gold job runs on dev and on production (daily 09:30 UTC, after the bronze job),
deployed by its own workflow. All 13 portable models give identical rows on Databricks and on DuckDB on a real fixture, and a rerun is idempotent; both run in CI
(see "The DuckDB comparison" below). Planned and not built: category and label dimensions with bridges, two daily facts and a brand scorecard.

Gold is built from silver only, by its own job and its own principals (`packsense-gold-dev`, `packsense-gold`), so the single-writer rule
holds: the bronze principal never writes gold, and gold never reads bronze, quarantine or the secret scope `packsense`.

## What exists
- **Project:** `dbt_project.yml`, `profiles.yml` (no secrets: host, warehouse path and credentials come from the environment), `requirements.txt` (pinned dbt).
  dbt lives in its own virtual environment (`.venv-dbt`): installing it next to the Databricks SDK in the main one downgrades the SDK.
- **Databricks-only staging** (`models/databricks/`, with DuckDB twins in `models/duckdb/`): `stg_silver_versions` (drops the 11 `egress: never` columns, keeps a count of distinct editors in
  their place, adds timestamps, the delta file's window, a GTIN-14 form, the GS1 prefix, a check-digit flag, the first brand and `tracked_hash`),
  `stg_flag_occurrences`, `stg_history_markets`, `stg_history_allergens` and `stg_taxonomy_names` (array and map explodes), and `stg_taxonomy_tag` (silver's taxonomy table).
- **Portable models** (`models/portable/`, plain ANSI SQL so they can run on DuckDB): `product_history` (SCD2 derived from silver's own versions, rebuilt in
  full every run: a period opens when the tracked set changes, versions that change nothing are merged, the open row is `is_latest_observed`),
  `product_flag_spans` (OFF's quality flags as spans, with `first_seen_is_first_version` and `vanished_with_tracked_change`), `product_status` (every
  product `unverified`, insert-only), `dim_brand`, `dim_market` (readable names, name matching) with `bridge_product_market`, `dim_date`, `taxonomy_tag_latest`, `taxonomy_name_lookup`,
  `dim_flag`, `bridge_product_allergen`, `dim_allergen` and `mart_allergen_change_log` (see "Taxonomy-based models"), and `bridge_product_category`, `dim_category`, `bridge_product_label` and `dim_label` (see "Categories and labels").
- **Categories and labels** (slice 4, `bridge_product_category`, `bridge_product_label`, `dim_category`, `dim_label`): one bridge row per history period and tag, from one Databricks-only explode view
  (`stg_history_taxonomy_tags`, with a DuckDB twin). The two dimensions share the macro `tag_dimension` (the same tag / name / ambiguous / none resolution as `dim_allergen`) and carry the taxonomy's
  hierarchy (`parents`, `n_children`, `is_root`). **Measured on production before building (2026-10-18, estimates, not the built tables):** about 347,000 category and 119,000 label bridge rows
  (the earlier estimate of 2.5 million was wrong); 9,201 distinct category tags and 1,866 label tags; 97.1% of category rows and 98.5% of label rows are exact taxonomy tags; the name match would resolve
  541 more category tags (0.5% of rows) and 39 label tags, with 5 ambiguous category names and no ambiguous label. **No closure table:** OFF's `categories_tags` already lists a category's ancestors.
  The test `category_lists_hold_their_ancestors` (a warning, not a failure) checks it: 15 of 1,523 exact-category rows in the fixture (1%) miss a parent, and several are taxonomy renames under old
  periods (the lists say `en:fruits-based-foods`, the taxonomy now says `en:fruit-based-foods`), which is the stated reason it is a warning. Free text such as `en:Groceries` stays `none`.
- **The tracked set** is one macro (`macros/tracked.sql`): tag arrays are sorted and the nutrients map is hashed by sorted entries, so a pure reordering is not a change.
- **Tests:** 99 dbt tests (no duplicate periods, one open row per code, contiguous periods, versions merged equal silver rows, neighbouring periods differ,
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

## Taxonomy-based models (2026-10-17, measured on production)
Gold takes OFF's taxonomies from silver (`silver_taxonomy_tag`, one row per taxonomy, snapshot and tag; the loader is in `p2_lakehouse`), never from the landing files.
`taxonomy_tag_latest` keeps the newest whole snapshot of each taxonomy listed in the var `gold_taxonomies` (countries, data_quality, labels, allergens).
- **Markets** (`dim_market`): a readable name and OFF's two-letter and three-letter codes (OFF uses `UK` for the United Kingdom, ISO says `GB`). Of 259 raw country tags,
  220 are canonical OFF tags, 12 are resolved by name (`en:Türkiye` to `en:turkey`) and 27 stay unresolved: malformed fragments such as pieces of escaped JSON.
- **Quality-flag families** (`dim_flag`): the family is the flag's first parent in OFF's data_quality taxonomy. Of 779 distinct flags, 475 have a family, 2 are top-level
  tags and **302 are `unmapped`**: OFF generates many flags in code (the per-source nutrition checks, for one) that the taxonomy file never lists. They are 6% of the 1.09 million
  flag spans, and no family is guessed for them. **A flag is not one severity:** 24 of the 779 appear under two (for instance a warning on some products and an error on another),
  so the dimension has `has_error`, `has_warning`, `has_info`, `has_bug` and `n_severities`; the severity of a span is in `product_flag_spans`.
- **Allergens** (`bridge_product_allergen`, `dim_allergen`, `mart_allergen_change_log`): one bridge with a relationship column (`contains` from `allergens_tags`, `may_contain`
  from `traces_tags`), 86,681 rows. The change log lists, for every product and every pair of consecutive history periods, the allergen tags added or removed: 1,034 changes in 372 products.
  The tags are typed by people: of 1,727 distinct allergen tags only 25 are canonical. A deterministic **name match** (below) resolves 310 more (`en:Milch`, `fr:lait`, `en:Senf`), and 1,392
  stay free text. The recognised share is 96.9% of bridge rows but **89.9% of change-log rows** (86.3% before the name match), because hand-edited tags concentrate in changes. A food-safety
  reader filters on `allergen_match_type` in (`tag`, `name`) and groups on `canonical_allergen_tag`.
- **The name match:** the text after the language prefix (which is ignored: `en:Milch` is German) is compared, ignoring case, with a taxonomy tag's name in any language
  (`taxonomy_name_lookup`). `match_type` is `tag`, `name`, `ambiguous` (the name belongs to several tags: no canonical tag is chosen) or `none`. It is deterministic and never fuzzy.
  The unrecognised remainder is free text and ingredient words (`Weizenmehl`, `Laktose`, `Molkenerzeugnis`); mapping those (wheat flour to gluten) is a food-safety judgement left undone.
  Every comparison of written names uses the macro `name_key`, because Databricks and DuckDB lower-case a few characters differently (see below).

## The DuckDB comparison (design 6.6)
The portable models must not depend on Databricks. The Databricks-only staging cannot run on DuckDB, so the comparison starts one step later:
- **The fixture** (`fixtures/stg_silver_versions.jsonl` plus `manifest.json`): the output of `stg_silver_versions` for 209 real products (510 versions, 24 of them added for real name-variant tags),
  chosen by a deterministic query (`notebooks/export_fixture.py`, ordered by md5 of the barcode) to cover one version and many, a no-op pair, a `rev` gap,
  legacy nutrition, seed-plus-delta overlap, vanishing flags, India and other markets. It carries the columns that need Databricks functions
  (`tracked_hash`, `first_brand`, GTIN-14, check digit, `distinct_editors`), so those are **carried, not recomputed, on DuckDB**: the comparison tests the
  portable models, not the hashing. A second file pair (`taxonomy_tag.jsonl`, `taxonomy_manifest.json`) holds 432 real taxonomy rows: the tags the products use, their parents
  and the canonical tags that name matches resolve to, every snapshot (labels has two, so "newest snapshot" is tested on real data); it leaves through `prepare_vocabulary_for_export`.
- **It left through the exit function** (`silver_lib/egress.py`, its first real use): no hashed column, scrub patterns removed, known contributor names
  replaced (19 rows), then written. Tests fail if the export notebook writes before the exit function ran or writes anything but its result, and if the
  committed file holds a hashed column or a scrub pattern. **Limit found:** the exit function counts "ordinary words" (names used in 10 or more products)
  over the exported rows only, so on a small export it over-redacts: one country tag (`en:<country>`) became `en:‹user›` in one product. A real public
  export should pass a catalogue-wide list of ordinary words. The fixture is real Open Food Facts data (ODbL, attribution: Open Food Facts contributors,
  <https://world.openfoodfacts.org>); it is the standing test asset, regenerated only when the staging shape changes or a new edge case is wanted (silver grows
  daily, so a regeneration picks a different slice).
- **Two engines, same models:** `models/databricks/` and `models/duckdb/` hold the staging views, exactly one folder enabled per engine (`dbt_project.yml`);
  the DuckDB twins use `unnest` and `list_distinct`. Per-engine macros (`macros/engine.sql`: ISO weekday, weekday name, distinct array size, first element, map get, `name_key`) cover the rest.
  On Databricks the fixture is loaded into a throwaway schema (`bootstrap/fixture_databricks.py load`, dbt target `fixture_admin`, var `fixture_mode`); on
  DuckDB by `gold_lib/fixture_load.py`, with the manifest's exact column types.
- **The comparison** (`bootstrap/compare_engines.py`): each row of seventeen models is reduced to a canonical form (integers by value, timestamps as UTC seconds,
  maps by sorted key, arrays in order) and hashed; `fixtures/golden.json` holds one hash per row from the Databricks run. A DuckDB run must reproduce every
  hash. **Result 2026-10-18 (fixture of 233 products, 542 versions and 1,236 taxonomy rows):** identical on all 17 models (product_history 353 rows, product_flag_spans 2,293, product_status 233, dim_brand 187, dim_market 64, bridge_product_market 623,
  dim_date 8,766, dim_flag 153, taxonomy_tag_latest 723, bridge_product_allergen 626, dim_allergen 55, taxonomy_name_lookup 13,846, mart_allergen_change_log 30, bridge_product_category 1,598, dim_category 420,
  bridge_product_label 824, dim_label 153), and all 123 dbt nodes (24 models, 99 tests; 122 pass, 1 warning) pass on both engines. The 2026-10-17 result was 13 models on 209 products. **The comparison found two defects:** (1) Databricks' statement API returns numbers nested in a map as text, a defect of the
  comparison reader, fixed and tested; (2) the engines lower-case a few characters differently (Databricks turns the Turkish dotted capital I into `i` plus a combining dot, DuckDB into a
  plain `i`), which made the name lookup differ for 13 Turkish and Azerbaijani names: fixed with the shared `name_key` macro and a test that forbids a bare `lower(trim(`.
- **Rerun idempotence** (`compare_engines.py idempotence`, 2026-10-17): on DuckDB a second build, a `--full-refresh` build (the incremental
  `product_status`) and a build from the same rows stored in the opposite physical order (the seed arrived after newer deltas) all reproduce the first build
  exactly, and the reversed build still equals the Databricks golden file.
- **Slim CI** (`engines` job in `ci.yml`, not a required check): parse the Databricks project in both modes, build the portable models on DuckDB, compare with
  the golden file, run the idempotence check. **To regenerate** after a model change: `fixture_databricks.py load`, `dbt`, `compare_engines.py dump --engine databricks`, `drop` (all
  with `--env-file .env`, run with `.venv-dbt`), then commit `golden.json`. A fixture change first needs `run_export_fixture.py` (products), then the same with `--notebook export_taxonomy_fixture`, then `fetch_fixture.py`.
- **Not covered:** `tracked_hash` and the Databricks staging logic themselves (tested by the Databricks-side dbt tests on real data), and the scheduled job.

## Still to do
`fct_product_change_daily`, `fct_catalogue_quality_daily` and the brand
scorecard. The per-market export and the public-site marts belong with P6 (they go through the exit function), the worklist mart waits for P7. Parked: an allergen alias table and a rule
table for the roughly 300 generated flags the taxonomy does not list.

## Gold principals and grants (set by an admin in the SQL editor, kept here so they can be re-created)
Two principals, each with the **Workspace access** and **Databricks SQL access** entitlements, **Can use** on the SQL warehouse and nothing else.
Replace `<principal>` with the application (client) id. A principal reads exactly three silver tables and writes only its own gold schema:
it has no access to bronze, to quarantine, or to the secret scope `packsense`. No `CREATE SCHEMA`: an admin creates the schema first.
Unity Catalog has no `CREATE VIEW` privilege; `CREATE TABLE` covers views.

Prod (`packsense-gold`; schema `workspace.packsense_gold`):
```sql
CREATE SCHEMA IF NOT EXISTS workspace.packsense_gold;
GRANT USE CATALOG ON CATALOG workspace TO `<principal>`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense_silver TO `<principal>`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_product_versions TO `<principal>`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_manifest TO `<principal>`;
GRANT SELECT ON TABLE workspace.packsense_silver.silver_taxonomy_tag TO `<principal>`;
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
production runs through the job as `packsense-gold`. Deploy by hand: from `p4_modelling`, `databricks bundle validate|deploy|run gold_build -t dev|prod` as the matching principal.

## Deploy workflow (`.github/workflows/deploy-gold.yml`)
On a push to `main` that changes the bundle (databricks.yml, resources, notebooks, gold_lib, models, macros, data_tests, dbt_project.yml, profiles.yml) or by hand:
job `dev` (environment `dev-gold`, principal `packsense-gold-dev`), then job `prod` (environment `prod-gold`, principal `packsense-gold`, after the reviewer approves).
It deploys the fixed copy and the job definition only; the scheduled job does the build (and a deploy resets the schedule to `gold_cron`). A separate workflow and
separate environments from the bronze deploy on purpose: each environment holds only its own principal's `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET`
(the host is the shared repo variable). `prod-gold`: deployment branch `main`, required reviewer, no administrator bypass; `dev-gold`: deployment branch `main`.
**The principals' OAuth secrets last 30 days (made 2026-10-17, expiring about 2026-11-16): rotate them in Databricks, in the gold scope and in the matching environment.**
A new workflow file can be run by hand only once it is on `main`.
`dbt parse` works offline with dummy environment variables; `dbt compile` and `run` need a real warehouse.

DuckDB check (no warehouse, no secrets), from the repo root:
```
.venv-dbt/Scripts/python -m pip install -r p4_modelling/requirements-duckdb.txt
cd p4_modelling
../.venv-dbt/Scripts/python -m gold_lib.fixture_load --db target/fixture.duckdb
../.venv-dbt/Scripts/dbt build --target duckdb --profiles-dir .
../.venv-dbt/Scripts/python bootstrap/compare_engines.py check
```
