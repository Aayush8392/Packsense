# p6_serving

The public site: aggregates of the gold tables, published as static pages. Built from public-class data only, behind the exit function and the licence gate.

## How data reaches the site (decided 2026-10-21)

```
gold (Databricks) --[job packsense-publish, 09:00 UTC, runs as packsense-publish]--> private Hugging Face dataset `site/`
                  --[workflow pages.yml, read-only token]--> Evidence build --> GitHub Pages
```

A staging dataset sits between the two services on purpose: no GitHub token lives in Databricks and no Databricks credential lives in GitHub. The publish job refuses
to upload when the licence gate finds anything; the Pages workflow verifies every file against the manifest and runs the gate again on what it fetched.

## What is exported (`export_spec.yml`)

Exactly three gold tables and one operating table, a listed set of columns each, nothing else (a column that is not listed cannot leave; a test fails if a listed column is classified personal
or internal): `brand_scorecard` (ranked brands only, no per-brand error counts), `quality_daily`, `change_daily`, and `pipeline_health` (90 days of job runs, durations and
whether each outside service answered, written daily by the admin-owned job `packsense-health`; a dataset with a `schema` key is read from that schema instead of gold), plus one `site_status` row and `ATTRIBUTION.md`.
Counts of 1 to 4 in the listed count columns are blanked (small numbers). Limit, stated on the site: a blanked cell can sometimes be recovered from a total beside it.
`export_lib.py` does the work (pure Python, tested on real rows of the DuckDB fixture); `notebooks/publish_site_data.py` reads the tables and uploads.

**Why the exit function gets no contributor-name list here:** the only names it could replace are contributor names of 8+ characters that are not ordinary words (a
word in the text of 10+ products). Every exported brand has at least 30 products, so every word of its name is ordinary by the exit function's own definition. A
test keeps the ranking floor at or above the contract's threshold. What the exit does here is the pattern scrub and the residue scan.

## Product cards for the barcode lookup (`card_shards` in `export_spec.yml`; roadmap Phase B item 12, 2026-10-23)

The same publish job also writes one small file per barcode prefix from the gold table `mart_product_card` (derived facts only: no product text, no image, no contributor data; every value is an
enumerated code, a small count or a time). The first 3 digits of a barcode name the file (`cards/406.csv`); any file larger than 150 KB is split by one more digit, repeatedly (up to 6 digits), and
`cards/splits.json` lists the prefixes that were split. **The lookup rule** (`licence_gate.shard_for`, written out in the app): take the first 3 digits; while that prefix is in the split list, take one more
digit; fetch `cards/<prefix>.csv`; a missing file means "not in our copy". Sizes measured on production on 2026-10-23: 155,134 cards are 14.2 MB as text (about 91 bytes each); the `890` (India) prefix alone
holds 20,062 cards. A year of growth is estimated at 0.8 to 2.0 million cards (inferred from three weeks), which is why the shards are adaptive: no file ever exceeds the cap, however many cards there are.
Only barcodes of 8 to 14 digits are published (the number dropped is in the manifest report). The licence gate has its own rule set for card files (exact columns, value domains, sorted unique barcodes that
belong to their file by the lookup rule, a size cap, no free text; the barcode column is left out of the Aadhaar-pattern re-scan because a 12 or 13 digit barcode looks like an Aadhaar number). The files go to the
staging dataset in the same commit (stale shards are deleted in it), `fetch_site_data.py` fetches them in parallel and verifies every one against the manifest, and `pages.yml` copies them to `/cards/` on the site.
The publish principal needs `SELECT` on `mart_product_card` (`p5_governance/grants.yml`, with a nightly policy check). The card wording and the traffic-light codes are in the p4 README.

## Identity

The job runs AS `packsense-publish` (a dedicated principal, `run_as`, no stored secret). Its grants are in `p5_governance/grants.yml`: SELECT on the three tables, USE on
the catalog and the gold schema, READ on the scope `packsense_publish` (the Hugging Face write token and the ping URL). It cannot read the product history, silver or bronze;
the nightly policy job proves it (`packsense-policy-publish`). The bundle (`databricks.yml`) is deployed by the admin from the laptop, like the policy bundle.

## One-time setup (admin; values typed at hidden prompts)

1. Create the private dataset repo on Hugging Face and two fine-grained tokens scoped to it: one WRITE (for Databricks), one READ (for GitHub).
2. A healthchecks.io check `packsense-publish` (1 day, 8 h grace; its ping URL goes into the scope).
3. `python p6_serving/bootstrap/setup_publish.py create-principal --env-file .env`, then `create-scope`, then `put-secret --name hf_site_token` and `put-secret --name healthchecks_publish_ping_url`.
4. `python p5_governance/bootstrap/apply_grants.py apply --env-file .env` (adds the grants), commit the client id the script wrote into the four bundle files.
5. From `p6_serving`: `databricks bundle deploy`, then run the job once with `dry_run=true`, then once for real; unpause by setting `publish_pause` to `UNPAUSED`.
6. GitHub: secret `HF_SITE_READ_TOKEN`, variable `HF_SITE_REPO`, Pages source set to GitHub Actions. Redeploy the policy bundle (`p5_governance`) so the new principal is tested nightly.

## The site (`site/`)

Evidence (open source, pinned: `@evidence-dev/evidence` 40.1.8, lock file committed; `npm ci` in CI). Pages: overview with build timestamp, brand scorecard, quality over time,
daily changes, pipeline health, about (licence, method, limits). Every page carries the Open Food Facts attribution; every page shows only data of the staged files, which are
fetched at build time and never committed. To preview with the committed test rows: build a release from `tests/fixtures/gold_rows.json` with `export_lib.build_release`, copy the CSV
files into `site/sources/site/`, then `npm run dev` in `site/`.

## The India release (`release_spec.yml`, `release_lib.py`, `release/`; Phase B item 11, built 2026-10-22)

A monthly, versioned, product-grain data release of the India catalogue (ODbL) on a PUBLIC Hugging Face dataset (`release.hf_repo` in the spec). One CSV, a generated data card
(`README.md` of the dataset) and a generated changelog; both carry the Open Food Facts attribution and numbers computed from the release itself.

- **Source:** the gold mart `mart_india_release`: one row per India product as last observed, without the products OFF said are gone (`confirmed_not_found`, `moved_other_type`).
  No images, no ingredient text, no hashed contributor column, no editor count. Tag lists are written joined by `|`.
- **Identity:** the job `packsense-release` is ADMIN-owned (no `run_as`), deployed from the laptop (`cd p6_serving/release`, `bundle deploy`). The exit function needs the plaintext
  contributor names, which only bronze holds, and no narrower identity may read them. The names live in the job's memory while the release is built and are never written or printed.
- **Ordinary words:** a name counts as an ordinary word when it is a whole word in the text of 10 or more products of the WHOLE catalogue (all markets), not only the exported
  rows (`release_lib.catalogue_ordinary_names`, passed to `egress.prepare_for_export(ordinary_extra=...)`). This closes the gap that a small export over-redacted.
- **Last step:** the licence gate runs on the rendered folder; a violation raises and nothing is uploaded. The upload is one commit plus a tag `vYYYY-MM-DD`.
- **Schedule:** monthly (the 3rd, 10:30 UTC), UNPAUSED since 2026-10-22 (it started paused until the first releases were checked).
- **Setup (admin, hidden prompts):** `setup_release.py create-scope`, `put-secret --name hf_release_token`, `put-secret --name healthchecks_release_ping_url`; then `apply_grants.py check`
  (the scope is in `grants.yml`) and a redeploy of the policy bundle.
- **Limits stated in the data card:** a snapshot of crowd-edited data; phone-number shapes are not scrubbed; the personal-data claim is a measured bound (`PRIVACY_AUDIT.md`), not a guarantee.

## Tests

`python -m pytest p6_serving/tests`: the column rule, the exit function, suppression, deterministic files, the gate stopping an image and a future date, the bundle wiring and
grants, and the fetch script against a fake Hugging Face. Not covered: the Databricks run itself and the Evidence build (a build runs in the Pages workflow).
