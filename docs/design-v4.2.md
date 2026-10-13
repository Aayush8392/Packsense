# PackSense: architecture (design v4.2)

- **Status:** frozen architecture. Every claim here was checked on real accounts with real data before the design was frozen (see section 14 for the verification summary).
- **Open on purpose:** two items are measured during the build, with fallbacks already decided: **C9** (a seven-day observation of GitHub's scheduled-workflow reliability, measured by the real capture workflow) and **C17** (an optional similarity-search demo).
- Section numbers are kept stable across versions so that references stay valid.

---

## 1. Summary

A daily-synced, cleaned, versioned, **multi-market packaged-food product catalogue**, India first, built from Open Food Facts (OFF), the open, crowd-edited database of about 4.8M products.

- **Problem:** every grocery, quick-commerce or nutrition app that uses OFF rebuilds the same ingestion: download nightly, clean messy multilingual data, keep a trusted versioned copy, publish its own catalogue, and watch for safety-relevant changes such as allergens.
- **What this adds:** that platform built the way an enterprise data team would, plus an ML layer that helps catalogue teams decide **which of OFF's ~31% flagged products to fix first**.

## 3. Constraints (final)
1. One combined project.
2. Generic and production-grade, with clearly defined usefulness.
3. **₹0 recurring cost.** No lapsing trials inside the project. Free *tiers* are allowed and tracked in section 13. No service in the main route needed a card.
4. Real data only. Fixtures are real slices; labels produced by the maintainer count as real.
5. Refresh cadence matches decision cadence.
6. Every tool has an enterprise or managed upgrade path.
7. **No raw or bulk data on the maintainer's workstation.** Allowed locally, small and listed in the README: programs (Docker, Airflow), logs (IDs and reason codes only), Label Studio's database, the Power BI file (aggregates only), Excel exports.
8. No local LLM.
9. **Each tool must have a real job the project needs**, not a workaround added to show a keyword. (Applied in this version: dbt Cloud, D1 + Worker, UptimeRobot, Gemini, Wikidata/USDA were cut; Airflow was narrowed; Neon was reframed.)

---

## 4. Users, outputs and cadence
| Output | User | Cadence |
|---|---|---|
| Per-market catalogue sync/export (new and changed products) | App / catalogue team | Daily |
| Allergen/ingredient change alerts | Food safety | Daily |
| Data-quality worklist ranked by the triage model; Excel export for brands | Catalogue ops | Daily |
| Steward-agent review queue (evidence + proposed fix; a human decides) | Catalogue ops | Daily |
| Public static dashboard: aggregates **and pipeline health and capacity** | Public / recruiters | Nightly rebuild |
| Static score lookup (barcode, score, provenance; browser demo) | Recruiters / app builders | Refreshed nightly |
| Brand/category completeness scorecard | Category managers | Monthly |
| India catalogue data release (ODbL; data card, changelog, quality report) | App builders / public | Monthly |
| Deletion reconciliation report | Platform | Monthly |
| *(Optional)* Time-to-fix analysis | Catalogue ops leads | Monthly |

---

## 5. Facts base (as of 2026-10-13)

### 5.1 Measured by us
| Fact | Detail |
|---|---|
| Delta publication | 13 consecutive daily files (30 Sep-12 Oct), no gaps, published 06:18-06:36 UTC; full dump ~06:48 UTC; 19-38 MB per file; kept 14 days; **no deletion flags** |
| One day's delta (5,013 products) | ~1,975 new; 561 products with India in any tag; 1,037 distinct top-level fields; 67 name languages |
| Nutrition format | 4,113 of 5,013 products carry only the new `nutrition` object (`input_sets` per source + `aggregated_set`), 876 both, 1 only `nutriments`. After 13 days: 80% of rows new-format. In the first GiB of the full dump, 39% of records carry `input_sets` |
| 13 days of deltas | 89,082 rows, **81,951 distinct barcodes**, 3,250 distinct India barcodes (3,500 India rows), **366 MB in bronze (~28 MB/day, ~10 GB/year)**. Open item: reconcile the 561-in-one-day figure with ~270 India rows/day on average (different definitions of "India-tagged") |
| OFF quality flags | 31% of changed products carry a nutrition flag; 133 flag types ≈ 59 check families; **no per-nutrient cross-source check in OFF's 1,248-tag taxonomy** (9 Oct 2026) |
| OFF's own tolerances | From OFF's open-source `DataQualityFood.pm`: kJ vs kcal `kJ < 3.7·kcal − 2` or `> 4.7·kcal + 2`; energy from nutrients error at ±30% + 5 and warning at ±15% + 5; salt vs sodium > 0.1 g; sugars > carbs (0.01 g under 10 g, else 0.1 g); any nutrient over 105 g; fat + carbs + protein + salt over 105 g; saturated > fat; energy over 3,911 kJ; **no dedicated all-zero-nutrients check** |
| Rules vs OFF flags (G1a, 81,951 products) | With OFF's exact conditions OFF's matching tag appears on kJ vs kcal 99.5%, salt vs sodium 99.6%, over 105 g 99.6%, total over 105 g 99.7%, kJ over 3,911 100%; energy-from-nutrients 81%/89% (our simplified formula), sugars > carbs 61% and saturated > fat 39% (our conditions ignore OFF's starch/trace handling: to verify). All-zero nutrients with energy: 60 products, 47 still carry an OFF energy/nutrient tag |
| Parquet (HF) | 4,793,952 rows (60 duplicate barcodes); rebuilt daily; its newest entry was 1.02 h older than our newest change; `nutriments` populated for new-format products (0 of 295 empty); **2.19% of recently changed barcodes are missing**: random 300 checked against OFF, **81% (CI 76-85%) deleted or merged, 19% (CI 15-24%) still exist**, flat by age of the change; the build race explains 41 barcodes (2.3%) |
| India seed | 24,736 products, 3.1 MB; 48% have a non-empty nutriments field (globally roughly 77% per Parquet footer statistics); 23 min to read remotely from Databricks |
| Dump transfer (B4) | `openfoodfacts-products.jsonl.gz` = 13,139,706,677 bytes, Range supported; 13 parts of 1 GiB into the private archive in **842 s** (~35 s download + ~19 s upload per GiB), 0 checksum mismatches; the first GiB expands to 6.68 GB (260,051 records, 90.6 s to parse): a full read is ~18 minutes on one node |
| Personal data | Usernames in ≥9 user fields (present in 100% of products, 5.25 distinct per product); free-text patterns in 0.8% of products (118 email, 564 phone, 0 Aadhaar/PAN; phone hits are mostly packaging codes and company contact lines) |
| Databricks Free Edition | Serverless jobs, git-sourced notebooks and dbt tasks; **scheduled runs on time (3 of 3)**; outbound internet open; admin/pipeline/analyst users; row filters and column masks work; secret scopes work; service principals can be created and used (OAuth M2M; no `run_as` binding); tokens can expire; MLflow tracking works, **UC model registry blocked**; `system.billing.usage`, job history and audit readable (billing rows lag by hours); no quota stop in any test |
| Unity Catalog quirks | Files API upload needs READ+WRITE on the volume; non-admins need `CAN_USE` on tokens; a filter argument named like a column silently made the filter always true; a service principal needs the `databricks-sql-access` entitlement |
| Hugging Face | Private archive confirmed; 13 daily files (371 MB) in one commit in 107 s; the 13 GB dump in 14 minutes; **free Docker Spaces return 402** (static only) |
| Backblaze B2 | No card; S3 API works with boto3; lifecycle rules work; a bucket-scoped `writeFiles` key uploads but is denied list/get, **and can hide (delete-marker) objects**; keys created with bucket scoping are usable only through the S3 API (native v2/v3 refuse them); **Terraform provider applied and destroyed cleanly in Actions** |
| Cloudflare | Workers AI answers in 0.6 s (LLM fallback only now); D1 + Worker measured at p50 ~640 ms from India and tested as a serving option, then rejected (section 0, #3) |
| Neon | 1 GB free; row-level security + masked view + restricted role work; a table-wide GRANT overrides a column REVOKE; review-store schema proven (role separation, optimistic concurrency, append-only audit); ~160 ms per statement from India, connect 1.3-2 s after idle |
| Groq / gateway | gpt-oss-120b answers in 0.8 s; headers show 1,000 requests/day and 8,000 tokens/min (200K tokens/day per the developer table); **Inference-API ZDR toggle exists and is now on (Batch and Fine-tuning storage toggles are off; they re-enabled themselves when ZDR was switched on and are checked again in the README's settings list)**; LiteLLM falls back to Cloudflare on a broken primary |
| Airflow 3.3.2 | ~1 GB RAM; started in ~4 min; reconciliation DAG: 300 mapped lookups, one pool slot, exponential backoff, a result file per barcode (resumable), ~25 min under OFF's rate limit; backfill DAG: 13 logical days, per-day counts sum exactly to bronze, one day cleared and re-run alone |
| Evidence | Open-source static site builds and deploys to GitHub Pages; ~87 MB build output (not committed) |
| dbt Cloud Developer | Free, no card, environments and scheduled jobs but **no API**; cut from the design |
| Labelling | 40 sandbox tasks labelled by a non-specialist; 18 of 20 flag cards were real errors; most flag cards needed the nutrition arithmetic explained, which is why rule-decidable flags are decided in code |

### 5.2 From official documentation
- OFF data page: nightly dumps, deltas kept 14 days, Parquet is a simplified JSONL, ODbL; OFF blog on the new nutrition structure; OFF's open-source data-quality code (for the tolerances above).
- Databricks Free Edition limitations page: quota-based compute, one 2X-Small SQL warehouse, non-commercial, inactive accounts may be deleted, no SLA. **Storage limit and daily compute quota are unpublished.**
- Groq rate limits and Data Controls page (without ZDR, Groq may store inputs/outputs up to 30 days); Cloudflare Workers AI does not train on customer content; HF storage limits (100 GB private); GitHub disables scheduled workflows after 60 days of repository inactivity.

### 5.3 Still unverified (mitigations in section 13)
GitHub cron reliability over a week (C9); the Databricks storage cap and daily quota; reading B2 from Databricks with credentials (A1 proved only that the endpoint is reachable); whether sugars > carbs and saturated > fat flags are missed by OFF or only by our simplified conditions; why ~16% of the missing set exist on OFF but not in the Parquet; Cloudflare Vectorize (C17, optional).

---

## 6. Architecture

### 6.1 Overview
```
 OFF (nightly delta + taxonomies; published 06:18-06:36 UTC)
        │
        ▼  GitHub Actions capture, 07:30 UTC (schedule + manual; at least daily)
        │  upload-only B2 key · pipeline-user token (landing volume only) · healthchecks.io ping
   ┌────┼──────────────────────────────┐
   ▼    ▼                              ▼
 Backblaze B2 (hot raw ~9 months,  Databricks UC volume landing/      Hugging Face private dataset:
  versioned; hidden files kept         │                              full raw history + ONE full JSONL dump
  30 days; alert on delete markers)    │      ▲ archive job (Databricks scheduler): B2 → HF in resumable
        └──────────────────────────────┼──────┘ parts + manifest; delete from B2 only after verification
                                       │
 DATABRICKS FREE EDITION — scheduled jobs, no local machine needed
   task 1 PySpark: landing → bronze (as received + manifest) → silver (contracts, both nutrition formats,
                   quarantine, HMAC usernames, lineage to bronze file + checksum)
   task 2 dbt Core: gold (star schema, SCD2, marts) + tests; written by a service principal
   Unity Catalog: roles · row filters per market · masks · secret scopes · MLflow tracking · system tables
   nightly: rule verdicts + ML scores → custom registry table → static score files
        │              │                    │                       │
        ▼              ▼                    ▼                       ▼
 Power BI Desktop  Evidence static     Monthly India          Neon Postgres: review queue, agent proposals,
 (RLS, aggregates) site on GitHub      release (HF dataset;   human decisions, audit trail
                   Pages: aggregates,  optional Zenodo DOI)   (governance fallback optional)
                   health, capacity,
                   static score files + browser demo (DuckDB-WASM)

 LOCAL WORKSTATION (Docker): Airflow 3 for four batch workloads (deletion reconciliation, backfill/rebuild drills, steward batch,
   gated release) · Label Studio · Power BI Desktop
 GitHub Actions CI/CD: lint · tests on real slices · security scans · dbt slim CI (Core) + DuckDB check
   (portable/) · Terraform plan/apply · Asset Bundle deploy dev→prod · tripwires
```

### 6.2 Components
| Job | Tool (free) | Runs on | Enterprise upgrade | If on AWS |
|---|---|---|---|---|
| Unattended core run and archive | Databricks Jobs scheduler (PySpark + dbt task; archive job) | Cloud | Databricks Workflows paid | Glue/EMR + Step Functions |
| Batch orchestration (reconciliation, backfill, steward batch, gated release) | Airflow 3, Docker, LocalExecutor | Local workstation | Astronomer / MWAA / Composer | MWAA |
| Daily capture | GitHub Actions (schedule + `workflow_dispatch`) | GitHub | Event-driven ingestion | EventBridge + Lambda |
| Hot raw storage and Terraform state | Backblaze B2 (S3 API, versioned) | Cloud | S3 / ADLS | S3 Standard |
| Archive | Hugging Face private dataset (+ Zenodo for releases) | Cloud | Glacier / Azure Archive | S3 Glacier |
| Lakehouse + processing | Databricks Free Edition | Cloud | Databricks paid | EMR Serverless + Lake Formation |
| Governance | Unity Catalog + HMAC | Cloud | UC paid | Lake Formation + Macie |
| Transformation | dbt Core (dev, CI, prod) | Cloud / CI | dbt Cloud Team | Same |
| Deployment | Databricks Asset Bundles via GitHub Actions | CI | Same | CodePipeline |
| IaC | Terraform (B2, GitHub, Databricks objects); state in versioned private B2 | CI | HCP Terraform | Terraform + S3 state |
| Review queue, decisions, audit (transactional) | Neon Postgres | Cloud | RDS / Aurora | RDS |
| BI (internal) | Power BI Desktop (RLS, aggregates) | Local workstation | Power BI Pro / Fabric | QuickSight |
| BI (public) and static serving | Evidence (pinned) + static files on GitHub Pages | CI | Hosted BI + API | QuickSight embedded + API Gateway |
| ML tracking + registry | MLflow tracking + custom registry table | Cloud | Databricks UC registry / SageMaker | SageMaker Model Registry |
| LLM access | LiteLLM → Groq (ZDR on) → Cloudflare Workers AI (OpenAI-compatible endpoint) | CI / local | AI gateway | Bedrock |
| Labelling | Label Studio Community | Local workstation | Label Studio Enterprise | Ground Truth |
| Monitoring | healthchecks.io, GitHub Action tripwire, Evidence status page | Cloud | Observability platforms | CloudWatch |

### 6.3 Storage
- **B2 (hot, versioned):** raw delta files and taxonomy snapshots for ~9 months (~30 MB/day ≈ 8 GB, under the 10 GB free tier; alert at 80%, with the threshold derived from the maximum observed in `system.billing.usage`-style measurements, not file sizes). Lifecycle: `raw/` hidden after 270 days, **hidden files deleted after 30 days** (not 1: an upload-only key can hide objects), `tmp/` hidden after 7 days. A tripwire counts delete markers and alerts on any that the lifecycle did not create.
- **Archive job (Databricks scheduler, daily):** copies files older than the hot window from B2 to HF in resumable parts with a manifest, verifies checksums, deletes from B2 only when verified. The mechanism is the one proven in B4 (1 GiB parts, a manifest written after each part, finished parts skipped on restart, HF's stored sha256 compared). **Build check:** reading B2 with credentials from Databricks (A1 only proved reachability); fallback: run the archive in GitHub Actions.
- **Hugging Face:** full raw history and **exactly one** JSONL dump (replaced, never accumulated). **There is no free second copy of the dump** (B2's 10 GB cannot hold it); a loss of the archive costs history, and the dump is a point-in-time state that cannot be recreated. Mitigation: Zenodo as an optional second home for the dump, with the transfer pattern above.
- **Databricks:** bronze/silver/gold Delta. **Bronze retention is the only storage lever** (silver for India is 3 MB; bronze is ~28 MB/day, but file sizes ranged 19-38 MB and Delta version history also grows). Retention, VACUUM and OPTIMIZE tuned against the unpublished limit; the nightly storage assertion is set from the observed maximum.
- **Seed:** India silver seed from the Parquet (24,736 products), backfilled from the JSONL dump for `input_sets` and the ~2% missing; reads run on Databricks. The dump is read once, part by part (about 18 minutes on one node), restartable per part.
- **Deletion reconciliation (monthly):** compare Parquet barcodes to silver; every candidate is confirmed against OFF before its history record is closed (a random check showed 81% are gone and 19% still exist). Closed records are marked, never erased.
- **Rebuild drill:** recreate silver from the archive; record RTO and RPO; assert that `flag_id`s are reproduced identically (6.7).

### 6.4 Ingestion and reliability
- **Capture** (07:30 UTC; never on `pull_request`): download the newest delta and taxonomies → checksums → upload to B2 (upload-only key) → push to the landing volume (pipeline-user token) → manifest → healthchecks ping. Re-runs are harmless (landing keyed by file name + checksum). The capture credential is upload-only and bucket-scoped and is never exposed to pull-request workflows (an explicit rule).
- **Core processing:** the Databricks schedule runs the job shortly after capture, with no local machine involved. The job is idempotent (manifest table + MERGE on code and last_modified_t; E3: a second trigger added 0 rows), so catch-up and re-runs are harmless. **Data-ready target 15:00 IST.** Airflow is deliberately **not** in this chain. A stop mid-run must leave Delta clean and the manifest honest: the manifest row is written only after the table write succeeds (verified in the build with a forced stop).
- **Schema-drift monitor (nightly):** a field-set diff against the previous day and coverage monitors (nutriments non-null %, `input_sets` presence %, `schema_version` distribution) with alert thresholds. Explicit schemas turn a renamed field into NULLs, so this is the control that notices.
- **Where Airflow is used (E4: batch work that tolerates delay and has real orchestration needs):**
  1. **Deletion reconciliation (monthly):** a sensor waits for the Parquet rebuild; candidates are confirmed against OFF through a rate-limit **pool** with exponential backoff and a result file per barcode (resumable).
  2. **Backfill and rebuild drills:** one run per OFF delta day (logical date), each calling a Databricks job; a failed day is cleared and re-run alone.
  3. **LLM steward batch:** per-provider pools respect Groq's 8,000 tokens/min and 1,000 requests/day.
  4. **Gated release:** dbt tests, privacy scan and licence check in order, then publish to HF and Pages, rerunnable from the failed step.
  Airflow stays only where it removes real code; if a review shows one of these is better as a plain script, it moves there.
- **Capture SLO and failover:** success rate and lateness of the 07:30 UTC capture are published. A named, executed failover (**CAP-F1**): Databricks can fetch the delta directly from OFF (A1), run once in the capture-failure drill and recorded in the failure-mode table. The healthchecks ping also fires on a successful site publish.
- **Catch-up:** the job processes every landed file it has not yet processed. If capture fails for more than 14 days (OFF's retention), it falls back to a full-dump comparison.
- **Tripwires (independent of any local machine):** a GitHub Action checks for today's file and for unexpected delete markers; healthchecks.io alerts on a missing ping.
- **Keep-alive:** the nightly status-page publish is repository activity (prevents GitHub's 60-day disable); a nightly Databricks job plus a weekly commit keeps the Databricks account active. A "gone six weeks" runbook narrative accompanies the drill.
- **C9 (open):** GitHub cron reliability is measured by the real capture workflow over its first 7 days.
- **Outage drills:** 3-, 10- and 20-day processing outages, one capture-failure drill (including CAP-F1), a mid-batch kill of the archive job, a Terraform state-recovery exercise, and one timed token rotation. Results go in a "failure mode → observed behaviour → recovery" table.
- **Hand-off checks:** row counts and checksums at every hand-off (GitHub → B2 → volume → bronze → silver).

### 6.5 Processing (Databricks serverless PySpark)
- PySpark DataFrames only; explicit schemas; `from_json`; barcodes as text.
- Both nutrition formats mapped into one silver contract, keeping per-source `input_sets`.
- Quarantine with the original record and a **coded** reason (not a descriptive one, which could leak content); quarantine payloads scrubbed of personal data; analysts cannot read quarantine.
- **Single writer per layer:** the PySpark job writes bronze/silver; **a service principal writes gold** (proven in E1b); grants and CI tests enforce it: the analyst and the pipeline user are denied writing gold, and the service principal is denied reading and writing bronze.
- **Lineage assertion:** every silver row carries the bronze file ID and checksum; a test checks the link.
- **Data contract** `contracts/silver.yml` (including a versioned `input_sets` contract), enforced in CI against real slices.
- **Compute-budget engineering:** per-job usage logging; the pipeline kept inside the free quota by design; classic Spark tuning demonstrated on small real samples with local Spark.
- A dbt task on serverless needs an explicit environment listing `dbt-databricks` (proven in C16); the service-principal path uses a notebook task with OAuth M2M credentials from a secret scope (E1b).
- **SCD2 note:** OFF publishes one row per product per day, so same-day edits are unrecoverable by construction. The India slice is edited about once per product per fortnight on average, which quantifies the collapse risk.

### 6.6 Modelling (dbt Core)
- `models/portable/` (ANSI SQL, compared against DuckDB in CI) and `models/databricks/` (platform-specific).
- Star schema: `dim_product` (SCD2 with `last_modified_t`), brand, category hierarchy, allergen, market, date; bridges product↔category and product↔allergen; facts `fct_product_change_daily`, `fct_catalogue_quality_daily`.
- Marts: per-market export, allergen change log, worklist, brand scorecard, public-site aggregates, India release.
- Tests: dbt tests + dbt-expectations; freshness and volume checks; **a snapshot test: no duplicate (business_key, dbt_valid_from) pairs after overlapping reruns**; docs on GitHub Pages.
- **Why DuckDB in CI:** it is fast and free, and it spends no Databricks quota; pull-request workflows from forks cannot see secrets and same-repo runs are kept off the warehouse by policy. (An earlier wording overstated this as "PRs cannot reach Databricks".)

### 6.7 Governance, privacy and access
- **Classification tags** on every column: public / personal / internal.
- **Personal data:** usernames in all user fields replaced in silver by HMAC-SHA256; removed from gold, dashboards, releases and LLM prompts; free-text fields scanned (email, phone, Indian ID patterns) and redacted before gold, **field-aware** (free-text fields only; ingredient text and customer-service fields included; packaging codes `emb_codes*` excluded from the phone pattern); **CI assertions:** no email or phone pattern survives in gold, the site or the release outside an allow-list of public company contacts, and no raw username appears in any logged prompt. A published **privacy audit** reports the measured numbers.
- **HMAC blast radius (stated in the README):** OFF usernames are public and enumerable, so a leaked key would let anyone re-identify contributors by hashing the public list. HMAC is deliberately unsalted so contributors stay joinable (5.25 distinct per product); key custody is therefore the single control: Databricks secret scope + GitHub secret + an offline escrow copy with a named location and access rule, and a rotation and re-scramble runbook executed once and timed.
- **DPDP wording:** "aligned with DPDP principles (minimisation, pseudonymisation)"; pseudonymised data remains personal data and nothing claims anonymisation or compliance.
- **Licence gate (CI):** every release, score file and site page carries the OFF attribution and ODbL notice with the source dump date in a manifest; **no product images** in any release, dashboard or public file; public score files contain only barcode, score and provenance (serving product fields would make them a Produced Work with wider notice duties); code stays Apache-2.0. The gate keys off the rendered output, not the spec that produced it.
- **Identities (all owned by the maintainer):** admin; pipeline user (read+write on the landing volume only); analyst test user; the gold service principal. Two-factor authentication and offline recovery codes on every owning account; tokens carry an expiry (Databricks supports it).
- **Row filters** by market (user→market mapping table) and **masks** on sensitive columns. **CI tests from lessons learned:**
  1. the analyst sees only their market (assert row counts per role; a filter argument must never share a name with a column);
  2. the analyst sees masked values in personal columns;
  3. the pipeline user cannot read tables or the secret scope;
  4. the analyst and pipeline user cannot write gold; the service principal cannot read or write bronze;
  5. on Neon, the restricted role cannot read personal columns (grant only safe columns; never rely on REVOKE after a table-wide GRANT);
  6. one Power BI page bound to a product-grain gold table with the filter active, with the row count recorded.
- **Review store (E5):** Neon Postgres holds the review queue, agent proposals, human decisions and an append-only audit trail. The steward agent can insert items and proposals but cannot decide or delete; the reviewer can decide but cannot delete decisions or edit the audit; one decision per item (unique); two writers use version-checked updates. Use batched inserts (a 40-row loop took 6.6 s).
- **Keeping the two stores honest (new):** a content-derived **`flag_id`** = hash(barcode, flag family, first-seen date); a rebuild must reproduce identical ids (asserted); the agent's evidence values are **snapshotted into Neon at proposal time**, so re-checking compares against the recorded snapshot and a separate drift job reports when silver now differs; a queue reconciliation step marks vanished flags *superseded* and never deletes (audit integrity).
- **Governance fallback (optional):** the same Neon database can serve RLS, a masked view and column grants if Unity Catalog ever fails (built and proven in C6).

### 6.8 CI/CD and infrastructure as code
- **Every PR:** ruff, sqlfluff, pytest on real slices, Airflow DAG import check, security scans (section 10), dbt slim CI + DuckDB comparison on `portable/`, `terraform plan`.
- **On merge to `main`:** Asset Bundle deploy (dev, then prod), `terraform apply` behind a protected environment, docs and public site published.
- **Terraform scope (the B2 provider is proven):** B2 bucket (versioned), lifecycle rules and bucket-scoped upload-only keys; GitHub repo settings, branch protection and secrets; Databricks schemas, volumes and grants. State in a **versioned private B2 bucket**, no locking (single-run concurrency group); bucket names are plain values, not secrets. A redacted resource inventory is committed to the repo so the infrastructure is documented even if state is lost.
- **Hygiene:** Actions pinned to commit SHAs; minimal `permissions`; secrets never exposed to `pull_request` workflows; Databricks CLI action pinned; narrower deployment identity than the admin token.
- **Token hygiene:** the verification tokens (admin, pipeline, analyst, B2 admin-scope key, GitHub, Hugging Face, Cloudflare, Groq, Neon) are revoked and replaced with narrower, expiring ones for the real repo, on a dated checklist, with one timed rotation drill. The three early runs that exposed the Hugging Face token as a parameter are a documented lesson; secrets reach jobs only through secret scopes.

### 6.9 BI and serving
- **Power BI Desktop:** analyst version with row-level security on aggregates (the PAT, filter and mask were proven to carry through) and one product-grain check (6.7).
- **Evidence (pinned) on GitHub Pages, rebuilt nightly:** public aggregates, **pipeline health** (last successful run per layer, rows landed, freshness) and the **capacity panel** (daily DBU by SKU and storage, job durations, B2 usage, Groq tokens, with days-until-cap forecasts).
- **Static score lookup:** the nightly job writes precomputed scores for India plus a few markets as static files on the same Pages site; a small browser page queries them with DuckDB-WASM. Responses carry only barcode, score and provenance. No server, no write budget, ~60-100 ms from a CDN. It is a precomputed lookup, not live inference, and the README says so. (The D1 + Worker alternative was built and measured in C8/C15 and rejected.)
- **Power BI Copilot is not used:** it needs a paid Fabric capacity or Premium; free licences and trials do not qualify, and constraint 3 excludes lapsing trials. The AI-assisted drafts in 7.9 cover the idea at ₹0.

---

## 7. ML / AI layer

### 7.1 Rationale
OFF already flags ~31% of changed products, and **with OFF's own tolerances its arithmetic checks fire on 99-100% of violations where they exist (G1a)**. So detection is largely solved. The gap is **prioritisation** and use of the new per-source nutrition data. The ML layer ranks, compares sources and matches products; it does not re-detect what OFF or a simple rule already detects.

### 7.2 Flag-triage model (core)
- **Finding to publish after the remaining checks (G1a):** over 81,951 changed products from 13 consecutive daily files, 11.9% break at least one arithmetic or physical rule under our own tolerances; under OFF's tolerances, OFF's matching flag is present on 99-100% of violations for kJ/kcal, salt/sodium, over-105 g, total-over-105 g and kJ over 3,911. Residual gaps are small (13 of 60 all-zero-with-energy products carry no OFF energy/nutrient tag; 9 of 86 products with kcal over 935 are unflagged). **To verify before claiming:** why sugars > carbs (61%) and saturated > fat (39%) are lower (starch/trace handling or real misses), and hand-check a 200-product sample. Claims are worded "across 81,951 recently changed products from 13 daily deltas", never "of OFF".
- **Rules first:** flags decidable by arithmetic or physics are labelled **by code** as `rule_error` (using OFF's own tolerances for the OFF-aligned ones). They are features and a high-precision baseline, not human work.
- **Unit:** a flag on a product, first seen on day *t*; features computed strictly as of *t* (flag family and severity, category, deviation size, edit history up to *t*, brand, source, completeness, rule verdicts, outlier scores and cross-nutrient residuals).
- **Weak label:** "fixed within *W* days": the flag disappears together with a value change **and the product still exists** (a flag also vanishes when a product is deleted or when OFF changes its tag taxonomy). The tag taxonomy is versioned per day, and labels are never compared across a taxonomy change without re-mapping. *W* set after measuring fix-time distributions (start 30 days).
- **Construct overlap, not just leakage:** rule verdicts as features and OFF's flag disappearance as the label are near-duplicates for several rules, so a high AUC can come from learning the mapping between taxonomies. The model's value is therefore reported **on the cases our rules do not cover** and on ranking within covered flags, and the README says so if the model only wins on covered rules.
- **Human labels (dozens):** only the flags the rules cannot decide, in the form "numbers are consistent, does the pack photo agree?" (real error / not an error / cannot tell). The 40 assisted sandbox labels measure the card design, not accuracy. **Gate:** 30 unaided re-labels a week apart; if self-agreement is below 0.8, no precision@k is published, only the rule baseline and the coverage table. With ~30 items a precision of 0.73 has a 95% interval of roughly 0.54-0.87, and the README says so.
- **Popularity** is not in the target; it is applied only at ranking. Precision@k is reported with and without it.
- **Baselines in order:** random; OFF severity; rule verdicts; our model without flag-family features; our model with them. The severity + rules ranking ships as a deliverable with a measured baseline before any history exists. If the last gap is small, the README says so.
- **Splits:** time only, reported per month (the schema migration guarantees drift). Calibration only where labels exist.
- **Cold start:** weak labels need weeks of captured history; until then, ranking uses severity + rule verdicts. This is why capture starts on day 1.
- **CI assertion:** max(feature timestamp) < label window start.

### 7.3 Source-disagreement detector (statistics)
- Compares `input_sets` (packaging vs manufacturer vs estimated) per nutrient with robust z-scores per (category, nutrient, source pair); versioned `input_sets` contract. A **minimum cell size** is set and the number of cells that clear it is reported, so the "normal disagreement" baseline is not fitted on noise.
- **Novelty claim (dated):** as of 2026-10-09, OFF's published quality taxonomy (1,248 tags) has no per-nutrient cross-source comparison. Because tags are not checks, the claim is also checked against OFF's source (the Nutri-Score producer-vs-calculated comparator) in the build.

### 7.4 Product identity matching (deep learning, optional depth)
- **Entity:** product = brand + line + variant; pack size is an attribute. Relations: **exact duplicate** and **family match** (same product, different size).
- **Blocking:** same brand + category + similar name, limited to target markets.
- **First step, before any labelling:** run blocking over the full India seed (24,736 products), count candidate pairs and a cheap positive proxy (same brand, category and nutrition vector, different barcode). If the proxy yields fewer than ~20 positives, the deliverable is "candidate generation with measured yield" and no accuracy claim is made.
- **Baseline first:** blocking + cosine similarity on a frozen multilingual embedding model; the baseline is the deliverable. **Fine-tune only if it beats the baseline,** as an appendix with negative results published. GPU: laptop RTX 3050 or Kaggle.
- **Labelling evidence:** 13 of 20 sandbox pairs were "same product, different size", so the options are: same product + same size / same product + different size / different product / cannot tell. Pair labelling needs no domain expertise.
- **Evaluation:** blocked candidate pairs; AP@k and recall@k within candidates; low base rate stated.
- **Optional live demo (C17):** Workers AI embeddings + Vectorize; the only reason a Worker would return, deferred.

### 7.5 Catalogue steward agent (pure review-queue assistant)
- **Input:** top-N ranked flags each night (N ≈ 50). The agent **annotates** the top-N; it does not order the worklist (the ranking is independent of the agent, which is the strongest defence against manipulation). **Tools (read-only):** version history, similar products, taxonomy, OFF flags, source disagreements. No internet; no write tools.
- **Output:** schema-validated JSON (diagnosis, proposed fix, evidence, confidence) into the Neon review queue. A human decides; nothing is auto-applied.
- **Evidence integrity:** field paths + verbatim values, snapshotted into Neon at proposal time and re-checked by code against the snapshot (6.7).
- **Injection defences:** product text and other editors' comments are wrapped as data; imperative constructions in tool outputs are neutralised by a cheap heuristic; raw tool output is logged so an auditor sees what the model saw; never rendered as markdown or links; a canary string in tool outputs; output schema validation.
- **No personal data in prompts, enforced at the tool layer:** user fields are projected out inside the tools, and a CI assertion checks that no raw username appears in any logged prompt.
- **Provenance:** model name, date, prompt hash and tool-output hash are stored with every proposal and feed the audit trail.
- **LLM via LiteLLM:** Groq gpt-oss-120b primary (**Inference ZDR enabled**) under a **token budget**: 50 items × (~3K input + ≤350 output) ≈ 167K tokens, against 200K/day per model, leaves ~16% headroom; the per-item budget is allowance × 0.8 ÷ N, tool outputs are truncated to it, and the sum is asserted before the first call (reduce N rather than fail mid-batch). Groq's 8,000 tokens/min allows about 2 calls a minute, so the batch is spread over at least ~25 minutes through a pool. Cloudflare Workers AI (OpenAI-compatible endpoint) is a per-call fallback with its own cap; **the model name is in config and tested nightly**. Two providers are enough.
- **Degradation:** if every provider is exhausted, the worklist still ships without annotations; calls per night are capped.
- **Evaluation:** proposals vs later community changes and agreement with hand labels.

### 7.6 Optional and later
Time-to-fix survival analysis at flag level (first-seen/last-seen from captured history); a revert-risk model (v2).

### 7.7 MLOps
- MLflow **experiment tracking** on Databricks; **custom registry**: model files in a UC volume plus a `model_versions` Delta table (version, metrics, data window, path, stage, approved_by). The README records the exact error that blocks the managed UC registry and shows the enterprise mapping.
- Nightly batch scoring deployed via Asset Bundles; output written as precomputed static score files. Drift monitoring (flag rates, score distributions, schema monitor). CI tests for ML code.
- **MLflow quirks:** do not `%pip install mlflow`; call `mlflow.set_registry_uri("databricks-uc")` before any other MLflow call.

### 7.8 Labelling
- **Tool:** Label Studio Community, run locally. Cards show names, images (in the local tool only) and key fields side by side; **the card pre-computes every arithmetic and physical check** (energy units, energy from nutrients, salt/sodium, totals, sugars vs carbs, energy ceiling, all-zero nutrients).
- **Rules:** a one-page labelling guide; the human only judges what the rules cannot (pack photo vs numbers) and product pairs. LLM pre-filled guesses are allowed, but the labeller confirms every label.
- **Volume:** dozens of flag labels (with the 30-item unaided gate in 7.2) and ~100-300 pair labels if the blocking yield in 7.4 supports it; the C11 sandbox labels (40) stay as a calibration set.
- **Storage:** labels database kept locally with a nightly export to the HF archive; **the export and a restore are tested once**, because every label-based metric depends on that database.

### 7.9 AI-assisted dashboard pages
- **What:** the LLM gateway drafts Evidence pages for gold marts from the **mart schema and a few aggregate rows only**. No product text, usernames or personal data go into the prompt. Every page carries its provenance (model, date, prompt hash, spec) and the SQL behind each chart in a tooltip.
- **Variant A (the real feature, propose-only):** the draft is a pull request. CI checks that every query uses an allow-listed mart, is read-only and returns aggregates; runs it against DuckDB on a real slice; fails on personal-data patterns, a missing OFF attribution/licence notice, or an empty chart. A human merges.
- **Variant B (an addition, unattended, only if it passes its gate):** the model returns a **JSON spec, never SQL**, restricted to a vocabulary of pre-approved columns with declared units and denominators; deterministic code renders the page from SQL templates over allow-listed marts; automatic checks (names exist, values in range, chart type fits, no personal-data pattern, attribution present, a gate that reads the rendered output); passing pages publish to a **separate, non-primary section labelled "AI-generated, unreviewed"**; takeaway sentences are templates filled with computed values. Failures are dropped and logged.
- **Test E6 (before adopting B):** **40 requests over real aggregates, adopted only at 90% or better with at most 4 failures.** (With 20 trials, 14 passes could mean anywhere from ~49% to ~94%, so the earlier gate could not separate a reliable generator from a coin flip.) Add a blind usefulness rating of ~20 pages by the maintainer. The failure mode that survives structural checks is a misleading but valid chart, so units and denominators are part of the vocabulary.
- **Fallback:** if every provider is exhausted, no draft is made; existing pages are unaffected. If E6 fails, Variant A alone remains.

---

## 8. Replacements for cut items
India catalogue release (monthly, versioned, ODbL, no personal data, data card, changelog, quality report; non-commercial, in line with Databricks Free Edition terms; the data card says a third party's commercial use is governed by ODbL on their side; optional Zenodo DOI) replaces Open Prices. Product identity matching replaces the recommender. Wikidata/USDA enrichment, UptimeRobot, Gemini Flash, dbt Cloud and the D1 + Worker API were cut under constraint 9.

## 9. Publication policy
Code Apache-2.0. Fixtures are small real OFF slices (ODbL with attribution, personal data removed). No full catalogue on GitHub. Releases ODbL with attribution and share-alike acknowledged, no personal data, no images. Public site aggregates only. A 24,736-product India slice is treated as a substantial part of the database, so the release is ODbL (no per-content DbCL argument is attempted). Short write-ups to publish: the nutrition-migration evidence, the **deletion and Parquet-gap finding** (random sample, 81% deleted, build race 2.3%), the **OFF check-coverage finding** (after verification), and the **"what I tested and what changed" list of defects** from section 4.3 of the review prompt.

---

## 10. Security baseline
Same checks for human and AI-written code; AI review is a second reviewer, never the only one.

| Layer | Controls | Free tools |
|---|---|---|
| Secrets | No keys in code; push protection; scoped, expiring tokens; secrets only via secret scopes (never job parameters); named key locations; HMAC escrow; rotation runbook with a timed drill; Terraform state remote, versioned | gitleaks, GitHub secret scanning |
| Dependencies | Locked versions with hashes; alerts; every new package checked as real and reputable | uv, Dependabot, pip-audit / OSV-Scanner |
| Own code | Static analysis; required PR review; branch protection | CodeQL, Bandit, Semgrep CE, ruff (S rules) |
| Containers / IaC / CI | Non-root, pinned digests, localhost-only ports, changed default credentials; scans of Docker, Terraform and workflows; SHA-pinned Actions, minimal permissions | Trivy, zizmor (Checkov overlaps Trivy's Terraform scanning and is dropped) |
| Data | Classification; HMAC on all user fields; field-aware scrub + CI assertion; one writer per layer; lineage to checksummed bronze; append-only bronze; audit table; retention; deletion handling; restore drill; delete-marker tripwire | dbt/UC tags, tests |
| Untrusted input | Schema validation, size limits, decompression guards, nothing executed from data, quarantine with coded reasons, schema-drift monitor | Spark schemas, contracts |
| AI agent | OWASP Top 10 for LLM Applications: injection handling (including third-party editor text), read-only tools, output validation, evidence snapshot checker, canary, no rendering, provenance logging, user fields projected out at the tool layer | LiteLLM, JSON Schema |
| Documentation | SECURITY.md; one-page THREAT_MODEL.md (secret leak, supply chain, prompt injection); DATA_CLASSIFICATION.md; incident runbook | OpenSSF Scorecard |

**Limit:** enterprise-like *controls*, not enterprise *assurance* (no external pen tests, certifications or round-the-clock monitoring). All identities belong to one person, so the owner's account security (unique passwords, two-factor authentication, offline recovery codes) is project security.

## 11. Design constraints and production mapping
| Constraint | Design response | Demonstrates |
|---|---|---|
| No always-on server | Independent cloud capture, scheduled Databricks core run, catch-up, tripwires, measured drills | Resilience under unreliable compute |
| Serverless Spark | Compute-budget engineering; classic tuning on local samples | FinOps awareness |
| No local storage | Tiered storage, resumable archive job, tested rebuild (RTO/RPO) | Disaster recovery |
| No paid cloud | Terraform on real resources (B2, GitHub, Databricks) | Practical IaC |
| No server for CD | Asset Bundles dev→prod | Real deployment pipeline |
| No free Power BI publishing | Evidence site with health and capacity panels + Power BI with RLS | BI as code |
| Masking needs identities | HMAC, tested access rules, dedicated identities including a service principal | Privacy by design |
| No Snowflake | `portable/` models checked against DuckDB | Warehouse portability |
| No dbt Cloud API | dbt Core in a Databricks task | Avoiding vendor lock-in |
| No UC model registry | Custom registry table + tracking | Registry design |
| No free live-inference host | Static precomputed scores queried in the browser | Cost-aware serving |
| No local LLM | Gateway with fallback, token budget arithmetic, per-provider evaluation, ZDR | LLM operations |

## 13. Free-tier dependency register
| Service | Purpose | Limits (as measured or known) | Card | Over limit | Fallback | Health check |
|---|---|---|---|---|---|---|
| Databricks Free Edition | Lakehouse, SQL, MLflow tracking, scheduler, archive job | Quota and storage unpublished; no stop seen in tests | No | Compute paused for the day | Archive rebuild; portable dbt | Nightly job + storage assertion + capacity panel |
| GitHub (Actions, Pages) | Capture, CI/CD, site, static scores | Cron best-effort; 60-day disable | No | Delays/skips | Manual dispatch; CAP-F1 (Databricks-direct fetch) within OFF's 14-day window | healthchecks.io, tripwire |
| Backblaze B2 | Hot raw store (versioned), Terraform state | 10 GB; delete markers possible with an upload-only key | No | Caps/bills | Absorb into HF + Databricks-direct reads. There is **no free second home for the 13 GB dump** (Oracle and R2 need a card) | Utilisation alert (80%), delete-marker tripwire |
| Hugging Face | Archive, releases | 100 GB private; static Spaces only; token scoped to the one dataset | No | Blocked/throttled | Zenodo for the dump and releases | Archive manifest check |
| Cloudflare Workers AI | LLM fallback | 10K neurons/day | No | Hard stop | Unannotated worklist | Call log |
| Groq | LLM primary (ZDR on) | 1,000 requests/day, 8K tokens/min, 200K tokens/day | No | 429 | Cloudflare | Token log + pre-flight budget assertion |
| Neon | Review queue, proposals, decisions, audit (+ optional governance fallback) | 1 GB, scale-to-zero (connect 1.3-2 s after idle) | No | Capped | a local Postgres | Connection test |
| healthchecks.io | Dead-man monitoring | Free tier | No | — | GitHub Action tripwire | Self |

A nightly **dependency-health job** exercises each service with a trivial call and publishes the results, with a 30-day history, on the status page, together with the **capacity panel** (6.9). The Databricks quota is unpublished, so the panel records observed behaviour and the README publishes it.

---

## 14. Verification results (summary; evidence in the project test log)
**41 test items were defined; 39 were executed against real accounts and real OFF data before this freeze.** 36 passed (several with findings that changed the design), 3 failed or partly failed and switched to a pre-agreed fallback (C4 model registry, C8 Hugging Face Space, C13 LinkedIn/GPU), and 2 stay open by design (C9 cron reliability, C17 optional similarity). Beyond the checklist, 40 labelling tasks were completed by the maintainer, and 81,951 real changed products, a 4.79M-row Parquet file and the 13 GB full dump were handled.

| Area | Items | Result |
|---|---|---|
| A. Deal-breakers | A1-A7 | All pass: outbound open; Files API push; Jobs API trigger; dbt Cloud connection (then cut); Power BI with a token; pipeline + analyst users; row filters and masks |
| B. Storage and data | B1-B5, B5b | All pass. B1 including the Terraform provider in Actions; B4 the 13 GB dump; B5/B5b a random-sample deletion rate with a confidence interval |
| C. Platform, tools, ML | C1-C3, C5-C7, C10-C12, C14-C16 pass; C4, C8, C13 fallback; C9, C17 open | Asset Bundles, secret scope, Terraform state in B2, Groq + gateway, Neon, Evidence, local Docker/Airflow stack, labelling (with changes), OFF timing, novelty claim, D1 scale (then rejected), scheduled Databricks dbt job |
| D. Consolidation | E1-E5, E1b, E7, G1, G1a, H1, T5 | Service principal proven end to end; usage tables readable; idempotent core; Airflow's remit; Neon review store; 1 GiB parse cost; token residue found and fixed; check coverage corrected; privacy scan field-aware |
| **Open by design** | C9, C17 | C9 measured by the real capture; C17 optional. **E6 (dashboard Variant B gate)** is a feature test in the build |

## 15. Build order (no timeline committed)
1. **Foundation:** repository; security baseline (pre-commit, CI scans, branch protection); **capture workflow running from day 1** (starts history and the C9 clock); tripwires (file freshness, delete markers); Terraform for B2 (versioned, 30-day hidden-file window) and GitHub; fresh narrow, expiring tokens and revocation of the verification ones (dated checklist); local Docker/Airflow stack.
2. **Lakehouse:** bronze/silver jobs, contracts, quarantine with coded reasons, HMAC + field-aware scrub, lineage, India seed load, schema-drift monitor, archive job on the Databricks scheduler (with the B2-from-Databricks check), Asset Bundles, scheduled core job; the one-time dump read for `input_sets`.
3. **dbt:** portable/databricks split, star schema, SCD2 with the snapshot-duplicate test, tests, slim CI, dbt as the gold service principal.
4. **Serving:** Unity Catalog roles and filters (with the CI tests of 6.7); Neon review store (E5 schema, `flag_id`, evidence snapshots); Power BI (including the product-grain check); Evidence site with health and capacity panels; static score files and the browser demo; first India release behind the licence gate.
5. **Operations:** drills (outage, rebuild, capture failure with CAP-F1, mid-batch archive kill, Terraform state recovery, timed token rotation), runbooks, dependency-health job, deletion reconciliation on Airflow.
6. **ML:** rule verdicts (OFF-aligned); labelling guide and card; the severity + rules baseline as a deliverable; triage with the lift-on-uncovered-cases reporting and the 30-item gate; source-disagreement detector; identity-matching blocking and yield count, then baseline; steward agent with provenance; custom registry; E6 for dashboard Variant B (Variant A first).
7. **Optional:** time-to-fix analysis; Zenodo DOI and a second home for the dump; C17 similarity demo; revert-risk (v2).

## 16. Known limitations (stated in the README)
- SCD2 is at daily granularity: OFF publishes one row per product per day, so same-day edits are unrecoverable by construction.
- Free-tier dependency: quotas and terms can change (mitigated in section 13, not eliminated); the Databricks storage and compute quotas are unpublished and most free-tier behaviour was observed over one day.
- GitHub cron is best-effort, so capture timing varies.
- Serverless Spark limits low-level tuning.
- Weak labels are noisy and partly construct-overlapping with our own rules; the triage model may largely mirror OFF's severity and the rule verdicts (reported honestly).
- Flag labels from the sandbox were assisted, so they measure the card design, not independent accuracy; precision@k is published only after the 30-item unaided gate.
- OFF's own arithmetic checks are near-complete where they exist; the project's contribution is prioritisation, a measured check-coverage comparison and the data findings, not a new detector for those rules.
- Identity matching has a low base rate and is a steward aid, not automatic dedupe; if blocking yields too few positives it is reported as candidate generation only.
- The score lookup is a precomputed static file, not live inference.
- The UC model registry is unavailable on Free Edition; a custom registry replaces it.
- The Parquet lacks ~2% of recently changed products (81% of those are deletions or merges) and per-source `input_sets`; the JSONL dump fills the latter. About 16% of the missing set exist but are absent from the Parquet for an unidentified reason.
- There is no free second copy of the 13 GB dump.
- Not covered: Snowflake, the AWS/Azure consoles, Kafka.
- Databricks Free Edition is non-commercial, so releases stay non-commercial.

## 18. Key sources
OFF data page and open-source data-quality code; OFF nutrition blog; Databricks Free Edition limitations; Groq rate limits and Data Controls; Cloudflare Workers AI privacy; Hugging Face storage limits and Spaces pricing; GitHub docs on disabling workflows; Backblaze lifecycle rules and Terraform provider; Neon pricing. (URLs as in v3, section 17.)
