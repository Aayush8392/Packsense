# Runbook: rotating the principal OAuth secrets

Four Databricks service principals sign in with an OAuth secret: `packsense-deployer` (GitHub environment `prod`), `packsense-deployer-dev`
(`dev`), `packsense-gold` (`prod-gold` and Databricks scope `packsense_gold`) and `packsense-gold-dev` (`dev-gold` and scope
`packsense_gold_dev`). The expiry alarm (`secret-expiry.yml`, check `packsense-secrets`) warns 10 days ahead. One script rotates all four:
`p3_delivery/bootstrap/rotate_principal_secrets.py`. It never prints a value; no secret or date list is kept in this repository (the list is
the repository variable `SECRET_EXPIRY_LIST`).

## What it does not rotate
`GH_TF_TOKEN` and the rotation token itself (GitHub has no API to create a personal access token), the admin and pipeline Databricks tokens,
the Hugging Face tokens, the B2 keys and the deploy key. Their expiry (or lack of it) is tracked in `SECRET_EXPIRY_LIST`; a soft reminder
date can be set with `set-expiry`.

## Before
- `.env` holds `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (admin) and `GITHUB_ROTATION_TOKEN` (fine-grained, this repository only, Secrets and
  Variables and Environments, all read and write). Use a fresh shell (a stale `DATABRICKS_CLIENT_*` is dropped by the script anyway).
- Choose a quiet time: not while a deploy or the gold build is running (06:45 to 08:45 UTC, 08:15 UTC gold, 16:00 UTC archive).
- `python p3_delivery/bootstrap/rotate_principal_secrets.py plan --all --env-file .env` changes nothing and shows, per principal: found, how many
  secrets it holds, which `SECRET_EXPIRY_LIST` entry it will move (`--expiry-name PRINCIPAL=ENTRY` when the name is not found), the GitHub
  environment reachable, the scope key present.

## Rotate
- Dev first: `rotate --principal packsense-deployer-dev --principal packsense-gold-dev --env-file .env`, then prove it (below), then
  `rotate --all` or the two prod principals. `--lifetime-days` defaults to 90 (Databricks allows up to 730).
- Per principal the order is: create the new secret; check it signs in; (gold) write the scope; write the GitHub environment secret and check
  its `updated_at` moved; move the expiry entry; delete the old secret. The old secret is valid until the last step, so a failure leaves a
  working system. A re-run creates another secret (limit five; the script stops at four): delete surplus ids in Databricks first.
- `--keep-old` leaves the old secrets in place (delete them later in Databricks, Settings, Identity and access, Service principals).

## Prove it (GitHub never returns a secret, so the proof is a run)
- `deploy.yml` by hand: the `dev` job proves `packsense-deployer-dev`; the `prod` job (needs your approval) proves `packsense-deployer`.
- `deploy-gold.yml` by hand: the same for `dev-gold` and `prod-gold`.
- `python p4_modelling/bootstrap/run_gold_prod.py --env-file .env`: the gold build reads the scope copy as the gold principal.
- `show-expiry` lists names and dates; the next `secret-expiry` run should be green.

## If something goes wrong
- A failure before step 4 of a principal leaves GitHub and the scope on the old secret (still valid): fix the cause and re-run.
- A failure after step 4 (GitHub already updated) leaves both secrets valid: re-run is safe; or finish by hand (move the expiry entry with
  `set-expiry NAME YYYY-MM-DD`, delete the old id in Databricks).
- Lost or leaked rotation token: delete it in GitHub (Settings, Developer settings), make a new one, put it in `.env`.

## Manual runs without a principal secret
After a rotation nobody holds a principal's secret, and none is needed: a bundle job runs as its owner whoever starts it. Use
`python p3_delivery/bootstrap/run_job.py --match <part of the job name> [--only TASK ...] --env-file .env` (admin token; proven on the dev gold
job, the dev bronze job's `drift` task and, earlier, the production gold and archive jobs). Deploys go through the manual **Run workflow** buttons of
`deploy.yml` and `deploy-gold.yml`. Do not run the dev bronze job's `capture` task: it would back-fill every file OFF lists into dev landing.
