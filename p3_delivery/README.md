# P3 Delivery: how the jobs are deployed

The two scheduled Databricks jobs (`packsense-bronze-load`: bronze, silver, drift; `packsense-archive`: archive, retention,
reconcile) are defined in an Asset Bundle: `databricks.yml` at the repo root plus `resources/` here. A deploy uploads a fixed
copy of the code to Databricks and the jobs run that copy, so a push to `main` no longer changes production by itself.

## Flow

1. A commit reaches `main` only after `tests` and `lint` pass (ruleset `require-ci`).
2. `.github/workflows/deploy.yml` runs on that push (when a bundle-relevant path changed) or by hand: **deploy dev**
   automatically, then **deploy prod** after a reviewer approves the `prod` environment.
3. Each environment holds its own principal's `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as environment secrets;
   `DATABRICKS_HOST` is the repo variable. The prod secret is only visible to the approved prod job.

Nothing is approved on a normal day: the scheduled runs keep using the deployed copy. Approval is needed only to ship a change.

## Targets

| | dev | prod |
|---|---|---|
| Principal | `packsense-deployer-dev` | `packsense-deployer` |
| Schemas | `workspace.packsense_dev_bronze`, `workspace.packsense_dev_silver` | `workspace.packsense_bronze`, `workspace.packsense_silver` |
| Landing volume | `workspace.packsense_dev.landing` | `workspace.packsense.landing` |
| Secret scope | `packsense_dev` (a throwaway HMAC key only) | `packsense` |
| Schedules | paused (development mode) | 06:45 UTC (capture, bronze, silver, drift, taxonomy), 16:00 UTC (archive) |
| Healthchecks pings | off | on |

Why two principals: on Free Edition a job runs as whoever deployed it and cannot be bound to another identity, so the deploying
identity is also the running identity. Separating dev from prod by permissions (not only by parameters) needs two principals,
each with rights on its own objects only. Schemas and volumes are created beforehand by an admin; no principal has `CREATE SCHEMA`.

## Grants
Both principals need the **Workspace access** entitlement and nothing else (no SQL access, no admin). Their grants, the admin's standing
`SELECT` on each pipeline schema (a schema owner gets no read access to the tables a principal created) and the secret-scope `READ`
entries are in `p5_governance/grants.yml`; `p5_governance/README.md` shows them as SQL and `bootstrap/apply_grants.py` applies and checks them.

## What the tests showed (2026-10-16, scratch)

- A principal with only Workspace access can sign in with OAuth, deploy a bundle and run a job; the job runs as that principal.
- Without `CREATE SCHEMA` the notebooks still work: `CREATE SCHEMA IF NOT EXISTS` on an existing schema is allowed.
- The notebooks find `silver_lib` and `archive_lib` in the deployed layout (they walk up from their own folder).
- Deploy state is per deployer: a local `.databricks` cache from another identity breaks a deploy (CI starts clean), and a root
  path under `/Workspace/Shared` is writable by every workspace user, so each target uses the deployer's own home folder.
- The drift notebook read production bronze whatever the target; it now takes `bronze_schema` like silver does.
- Serverless retries a failed task by itself. The drift task fails on purpose when it raises an ALERT, and the retry (which finds
  the day already judged) pinged OK and turned the check green within a minute, hiding the alert. The drift task therefore sets
  `disable_auto_optimization: true`; the other tasks keep their retries (their loads are idempotent).

## Limits

- The dev archive job is deployed (paused) but cannot work: the dev scope holds no B2 or HF keys. Do not add them.
- The principals' OAuth secrets expire (30 days when made; at most 730): one script rotates all four, including the GitHub environment secrets, the gold scopes and the expiry list: `p3_delivery/bootstrap/rotate_principal_secrets.py`, procedure in `docs/runbook-secret-rotation.md`. Built 2026-10-19; not yet run live (the first run is on the dev principals).
- Rollback is a `git revert` followed by a redeploy of the reverted code (the deploy workflow, or the CLI as the target's
  principal). Drilled on the dev target on 2026-10-16 (a silent data bug reverted, redeployed and the data repaired with
  `RESTORE`); the prod deploy of a revert and the production schedule pause are not drilled. See `docs/runbook-rollback.md`.

## Cutover of the production jobs (the old admin-owned jobs are replaced)

1. Grant the prod principal as above; pause the old job's schedule in the Jobs UI.
2. Deploy `-t prod` as the prod principal (a new job with the same name and the same schedule).
3. Run the new job once by hand, then watch one scheduled run succeed.
4. Delete the old job; the old `create_bronze_job.py` and `create_archive_job.py` scripts were removed on 2026-10-17 (done for both jobs).
