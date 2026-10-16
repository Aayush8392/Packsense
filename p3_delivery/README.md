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
| Schedules | paused (development mode) | 09:00 UTC (bronze), 16:00 UTC (archive) |
| Healthchecks pings | off | on |

Why two principals: on Free Edition a job runs as whoever deployed it and cannot be bound to another identity, so the deploying
identity is also the running identity. Separating dev from prod by permissions (not only by parameters) needs two principals,
each with rights on its own objects only. Schemas and volumes are created beforehand by an admin; no principal has `CREATE SCHEMA`.

## Grants (set by an admin in the SQL editor, kept here so they can be re-created)

Both principals need the **Workspace access** entitlement and nothing else (no SQL access, no admin). Replace `<principal>` with
its application (client) id.

Prod (`packsense-deployer`):

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<principal>`;
GRANT USE SCHEMA ON SCHEMA workspace.packsense TO `<principal>`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME workspace.packsense.landing TO `<principal>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_bronze TO `<principal>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA workspace.packsense_silver TO `<principal>`;
```

Secret scope `packsense`: `READ` for the principal (`databricks secrets put-acl packsense <principal> READ`).

Dev (`packsense-deployer-dev`): the same shapes on `workspace.packsense_dev_bronze`, `workspace.packsense_dev_silver` and the
volume `workspace.packsense_dev.landing` (with `USE SCHEMA` on `workspace.packsense_dev`), and `READ` on the scope `packsense_dev`.

**Owner grant for the admin.** A table is owned by the principal that created it, and a schema owner does not get read access to
it, so the admin needs a standing `GRANT SELECT ON SCHEMA <schema> TO <admin user>` on each schema to read what the jobs write.

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
- The principals' OAuth secrets expire (30 days when made; at most 730): rotate them and update the environment secrets.
- Prod rollback is a redeploy of an earlier commit (`git revert`, then the deploy workflow), not yet drilled with the bundle;
  see `docs/runbook-rollback.md` (sections C and E describe the old job scripts).

## Cutover of the production jobs (the old admin-owned jobs are replaced)

1. Grant the prod principal as above; pause the old job's schedule in the Jobs UI.
2. Deploy `-t prod` as the prod principal (a new job with the same name and the same schedule).
3. Run the new job once by hand, then watch one scheduled run succeed.
4. Delete the old job; retire `p2_lakehouse/bootstrap/create_bronze_job.py` and `p1_intake/bootstrap/create_archive_job.py`.
