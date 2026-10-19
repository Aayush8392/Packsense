# PackSense

A daily-updated, cleaned and versioned copy of the [Open Food Facts](https://world.openfoodfacts.org) product catalogue, India first, built the way a company data team would build it.

> **Status: build in progress.** The design is frozen (v4.2, [`docs/design-v4.2.md`](docs/design-v4.2.md)); intake, the lakehouse (bronze, silver, taxonomies) and the gold layer (dbt Core) are running on schedules. Nothing is published yet: no dashboard, no data release.

## What it does
- Picks up what changed on Open Food Facts every day, without any laptop being on, and keeps the full history.
- Cleans and stores the data in layers (raw, tidy, business-ready) on a lakehouse.
- Scrambles contributor usernames and checks that no emails or phone numbers slip through.
- Finds arithmetic and physical errors in nutrition data and ranks which suspicious products to fix first.
- Tracks products that disappear (roughly 1.8% of recently changed products are deleted or merged within days).
- Lets an AI assistant **propose** fixes into a review queue; a human always decides.
- Publishes a public dashboard with pipeline health, a monthly India data release, and a static score lookup.

## Principles
- ₹0 recurring cost, free tiers only, every limit tracked.
- Real data only, no synthetic data.
- No bulk data on a local machine; a workstation is a control point, not a warehouse.
- Every tool has a real job; nothing is here only to show a keyword.
- Everything claimed was tested on real accounts and real data first (41 verification items before the first commit of the build).

## Where it stands (2026-10-18)
| Built and running | Not started |
|---|---|
| Daily capture (GitHub Actions), landing volume, 34 taxonomy snapshots, freshness, delete-marker and secret-expiry tripwires, healthchecks.io monitoring | Per-market export and public-site marts (P6), worklist mart (P7) |
| Verified second copy of the raw files in a private Hugging Face dataset (daily job), landing retention (30 days) and a B2 reconciliation audit | Dashboard, static score lookup, India data release |
| Bronze (raw, append-only) and silver (typed, checked, scrubbed; data contract v4, 81 columns) as a scheduled Databricks job, deployed from an Asset Bundle | Triage model, steward agent, review queue |
| India seed from the full dump: 24,875 distinct India barcodes in silver | Access control policies and CI checks, Terraform for Databricks |
| Schema-drift monitor with its own alert | Airflow batch workloads, deletion reconciliation |
| OFF's taxonomies in silver (59,340 tags in 44 snapshots, allowlist contract) and gold (dbt Core, own principal, scheduled job and deploy workflow): product history (SCD2 derived from silver's versions), quality-flag spans with families, brand, market (readable names) and date dimensions, allergen, category and label bridges and dimensions with an allergen change log, daily change and quality facts, a brand scorecard, 137 dbt tests (165 nodes in production); the 20 portable models give identical rows on DuckDB and on Databricks on a real fixture of 233 products, checked in CI (not a required check) | Dashboard, static score lookup, India data release |

## Known limitations (measured, not hoped)
Each of these is a number from this project's own data, or marked as inferred.
- **Personal data: a measured bound, not a guarantee.** OFF contributor names are public and cannot be reliably told apart from ordinary words (a name-matching gate wrongly quarantined 3.15% of real products, so it was dropped). Silver keeps only two free-text columns (`product_name`, `brands`), scrubs patterns with a clear shape (emails, URLs, handles, Indian ID formats), and replaces the record's own contributor names of 8+ characters. Measured over 91,917 rows (2026-10-15): contact-shaped text in those two columns in 5 rows; known contributor names (8+ characters, not ordinary words) in 161 rows (0.175%), which the export step replaces; shorter handles of 5-7 characters in 530 rows are counted, not replaced. Re-measured over 135,062 rows (2026-10-18, counts only, per column): contact-shaped text in the raw `product_name` and `brands` in 10 rows (3 emails, 7 URLs; 9 names and 1 brand), and 0 rows in silver after the scrub. A run of 7 or more digits is **not** scrubbed (phone numbers are deliberately not matched by pattern) and stands in 701 product names (0.52%) and 16 brands; 8 names and 1 brand hold a 10-digit run in the shape of an Indian mobile number (counted by shape, not checked by eye). The known-name figure was not re-measured. The exit function that replaces names is built but wired only into the test-fixture exports: no release, site or prompt export exists yet. There is no name-recognition model, the attribution-phrase list covers five languages, and there is no process for data-subject requests. Hashed contributor codes protect against this project's own readers only: OFF publishes the usernames, so anyone can match a code to a name.
- **Not everything parses.** Of the non-empty values, 89.1% of `quantity` and 94.9% of `serving_size` become a number and a unit; the rest become NULL. About 2.2% of the tags in the four user-entered tag columns (10,046 of 453,932) fail the shape check and are dropped from silver; bronze keeps them.
- **India nutrition data is thin and mixed.** Of 24,795 India products in the dump (2026-10-13): 24.2% have the new nutrition format, 18.7% only the old format (mapped into the same columns, but without a per-100 g/ml basis or per-source breakdown), and 57.2% have no nutrition data at all, against roughly 77% across all of OFF (inferred from file statistics, not re-measured).
- **The seed is a snapshot.** It is one read of the 2026-10-13 dump; later changes arrive only through the daily files. Deletions are not tracked yet: about 1.8% of recently changed products disappear within days (measured earlier), and nothing here removes them yet.
- **Timing is not met yet.** GitHub's scheduler is best-effort: the five scheduled captures counted ran 5 h 27 min, 5 h 15 min, 5 h 5 min, 4 h 11 min and 4 h 37 min late with no skipped day (the 7-run window was closed at five by decision, since more runs would not change the answer). So the capture was made the first task of the Databricks job (2026-10-18): the job starts at 06:45 UTC, polls OFF until today's file is listed (OFF published the 13 deltas still listed between 06:19 and 06:33 UTC) and fails loudly at 07:45 UTC, with the GitHub capture kept as an independent second path; gold runs at 08:15 UTC. Until then (14-18 Oct) the processing job ran at 09:00 UTC before the capture had landed, so each day's data was processed a day late. How the new schedule performs is recorded after its first runs, not claimed here. A missed capture costs nothing inside OFF's 14-day window (the next run back-fills).
- **Free-tier dependencies.** Databricks Free Edition (non-commercial, unpublished storage and compute quotas), Backblaze B2 (the daily download cap was reached once during testing), Hugging Face. The 13 GB dump has no second copy. Only a small restore (3 of 56 files) has been drilled, not a full rebuild from the archive.
- **The drift monitor sees presence and shape, not meaning.** Its baseline is the last 30 days (17 held on 2026-10-18), and its thresholds (a 5-point margin, a failure-rate factor of 3.0) are initial estimates: replayed on those 17 days there are only two real events, and the second sits about 2% above the 3.0 line. It cannot notice a field that keeps its name but changes unit.
- **Names typed by people are messy.** Of 1,727 distinct allergen tags only 25 are canonical OFF tags. A deterministic name match (case-insensitive equality with a taxonomy name in any language) resolves 310 more (`en:Milch` to milk), and 1,392 remain free text: the recognised share is 96.9% of the allergen bridge but 89.9% of the allergen change log. 39 of 259 market tags were not canonical; 12 resolve by name, 27 are malformed fragments.
- **Quality-flag families are partial.** Of 779 distinct flags, 477 are in OFF's quality taxonomy (94% of the 1.09 million flag spans); OFF generates the rest in code, so they stay `unmapped` and no family is guessed. A flag can appear under several severities (24 of 779), so severity is a set of columns, not one value.
- **CI covers the unit tests and lint, not the pipeline.** On every branch push CI runs the unit tests (real, sanitised records; nothing touches Databricks or the network) and `ruff`, and `main` accepts a commit only after both have passed on it (a ruleset managed by Terraform; its single exception is a deploy key used by the keep-alive workflow, which cannot delete `main` or force-push it). Security scans (gitleaks over the history, zizmor on the workflows, pip-audit) run too but are advisory. The bronze and archive jobs ship from an Asset Bundle (dev automatically after a push to `main`, production after a manual approval); the gold job has its own bundle and deploy workflow (production after a manual approval). CI does not run dbt against a warehouse; its `engines` job builds the portable gold models on DuckDB and compares them with a golden file from Databricks (a fixture of 233 products; not a required check).

## Data and licence
Code is Apache-2.0 (see [`LICENSE`](LICENSE)). Data comes from Open Food Facts under the [ODbL](https://opendatacommons.org/licenses/odbl/1-0/); published data releases carry the required attribution and share-alike terms. Product images are not redistributed.

## Layout (grows as the build progresses)
```
p1_intake/       P1: daily capture, landing, taxonomy snapshots, tripwires
p2_lakehouse/    P2: bronze, silver, taxonomy tables, India seed, drift monitor on Databricks
p3_delivery/     P3: Asset Bundle job definitions, grants, rollout notes
p4_modelling/    P4: the gold layer (dbt Core), the DuckDB comparison fixture
infra/terraform/ infrastructure as code in two roots: b2/ (bucket, keys, derived secrets) and github/ (rulesets, deploy key)
docs/            design and evidence
.github/         workflows (they must live here), Dependabot, CODEOWNERS
```
Later modules get their own `pN_name/` folder when they start.
