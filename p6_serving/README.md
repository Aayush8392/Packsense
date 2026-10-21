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

## Tests

`python -m pytest p6_serving/tests`: the column rule, the exit function, suppression, deterministic files, the gate stopping an image and a future date, the bundle wiring and
grants, and the fetch script against a fake Hugging Face. Not covered: the Databricks run itself and the Evidence build (a build runs in the Pages workflow).
