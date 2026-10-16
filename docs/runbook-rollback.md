# Runbook: roll back a bad change

**Status: sections A, B and E drilled (A and B on scratch 2026-10-16, then A, B and E again through the bundle on the dev target the same night); C and D not exercised.** The steps are read from the repository (workflows, bundle, the re-key runbook) and from Delta Lake behaviour. The drills (see the end) reverted a deliberate silent bug with a real `git revert` and repaired the data with Delta `RESTORE`; the points they could not cover keep their **(unverified)** tag.

## Where changes ship today (Asset Bundle, since 2026-10-16)

A push to `main` no longer changes the scheduled jobs by itself: `deploy.yml` deploys a fixed copy of the code to dev, then to prod after a reviewer approves the `prod` environment (see `p3_delivery/README.md`). The jobs run the deployed copy.

| Thing | How a change reaches production | Takes effect |
|---|---|---|
| Notebooks and libraries (`p1_intake/notebooks`, `p2_lakehouse/notebooks`, `silver_lib/`) | `deploy.yml` uploads a fixed copy (dev automatically, prod after approval) | At the next run of the job that uses them, once the prod deploy is approved |
| Workflows (`capture.yml`, `freshness.yml`, `delete-markers.yml`, `keepalive.yml`, `ci.yml`, `security.yml`, `deploy.yml`) | GitHub reads the file on `main` | At the next trigger |
| Job definitions (task list, schedule, parameters) | `databricks.yml` and `p3_delivery/resources/*.yml`, shipped by the same deploy | Immediately on deploy; a deploy changes only what differs and keeps the job id |
| Infrastructure (B2 bucket, keys, repo secrets, `protect-main`) | Terraform workflow: a plan on pull requests, `apply` only on a manual dispatch behind the `terraform-apply` environment | When the apply finishes |
| Data (bronze, silver, quarantine, manifests) | Written by the jobs | At each run |

`main` allows no force-push and requires linear history, so a rollback is always a **new revert commit**, never a rewrite.

## Decide first: what broke?

1. **Code is wrong, no bad data written yet** (caught before the next run): revert the code (A).
2. **Code is wrong and a run already wrote bad data**: revert the code (A), then repair the data (B). Pause the job's schedule first so nothing writes while you work (Databricks UI, job `packsense-bronze-load`).
3. **A workflow change broke capture or a tripwire**: revert it (C).
4. **An infrastructure change is wrong**: revert and re-apply (D).
5. **A job definition is wrong**: revert the bundle file and redeploy (E).

## A. Revert code

1. `git log --oneline -10` and find the bad commit. If several commits belong together, revert each, newest first.
2. `git revert <sha>` (one commit per bad commit; do not squash different changes together).
3. Run the tests: `.venv\Scripts\python.exe -m pytest p1_intake/tests p2_lakehouse/tests`.
4. Push to a branch, let CI pass, then fast-forward `main` (the normal workflow). Since 2026-10-16 `main` requires the CI checks `tests` and `lint` on the commit it moves to (ruleset `require-ci`, Terraform), so even an emergency revert goes through a branch and a green CI first (CI runs on every branch push, about a minute). If CI itself is what broke, edit or disable `require-ci` in the repository's rule settings, fix, and turn it back on.
5. **The revert is not live until it is deployed.** The jobs run the deployed copy, so after `main` has the revert, `deploy.yml` must ship it: dev runs by itself, prod waits for the reviewer's approval of the `prod` environment. In an emergency, deploy by hand from the reverted checkout with the CLI (see E). To confirm, run the job once by hand (`databricks bundle run bronze_load -t dev` or `-t prod`) and read the result.

## B. Repair data after a bad run

**Principle:** Delta keeps table versions, so a table can go back to an earlier version. Bronze, silver and the two manifests are tied together: restoring one without the others leaves a lie. **Drilled on scratch: `RESTORE TABLE ... TO VERSION AS OF` returned the three silver tables to the state before a bad run in 18 s, and version 0 of a table stayed readable. Not verified: how far back the production tables' own history reaches (the project has never run `VACUUM`, and Delta's default keeps files for 7 days after a vacuum, so older versions should stay readable until one is run).**

1. Pause the daily job (`packsense-bronze-load`) and, if the archive wrote something wrong, `packsense-archive`.
2. Find the last good version of each affected table with `DESCRIBE HISTORY <table>` (timestamps and operations). Use the version just before the first bad run.
3. Restore all tables of the affected layer to the matching moment: `RESTORE TABLE <table> TO VERSION AS OF <n>`. The set to restore together:
   - Bronze problem: `bronze_delta_raw` and `bronze_manifest`. Silver and its manifest then also need a check (step 5), because silver may already have processed the bad rows.
   - Silver problem: `silver_product_versions`, `silver_quarantine` and `silver_manifest` (silver writes are insert-only, so a restored manifest is what makes the job redo the files).
4. Run the job once by hand with the fixed code (step 5 of A already done).
5. Verify against the same checks the verification runs use: row counts equal the figures before the bad run for the same files, manifests one row per file, no duplicate `(code, last_modified_t)`, silver rows join to bronze 1:1, drift task quiet.
6. Resume the schedule.

**Landing keeps delta files for 30 days only** (retention task of the archive job): older raw files exist in B2 (270 days) and the HF archive, so a rebuild of older data reads the HF archive.

If a table cannot be restored, rebuild: silver from bronze (the re-key runbook describes the rebuild, about 8 minutes on the full data), bronze from the landing volume or the HF archive (read the **HF archive**, not B2, because of B2's daily download cap).

## C. Revert a workflow change

1. `git revert <sha>` the workflow commit and push as in A.
2. For `capture.yml`: **never rename it** (the C9 history is tied to the file name). After the revert, run it once by hand (`workflow_dispatch`, branch `main`) and check its `head_branch` and `head_sha` through the API, because a dispatch can run on the wrong branch.
3. A failed capture costs nothing inside OFF's 14-day window: the next run back-fills missing files.

## D. Revert infrastructure (Terraform)

1. `git revert` the change under `infra/terraform/` and push.
2. Dispatch the `Terraform` workflow with `action = plan` on `main` and read the plan: it must show only the reversal. The plan needs the B2 admin key as a secret (it was deliberately removed): to run a full plan add the two secrets, run, then remove them again; the workflow's optional `target` input (for example `github_repository_ruleset.protect_main`) limits a run to one resource, which is how GitHub-only changes are applied without the B2 key.
3. Dispatch with `action = apply`; it waits at the `terraform-apply` environment. **(Reviewers must be added to that environment in the repository settings for the approval gate to exist: check before relying on it.)**
4. Safety net: Terraform state is in the versioned private B2 bucket `tfstate-aayush`; an older state version can be restored through the B2 console if a state file itself is damaged. **(unverified: the restore has not been exercised; the design lists a state-recovery exercise for P9.)**

## E. Restore a job definition (or redeploy earlier code)

Job settings live in `databricks.yml` and `p3_delivery/resources/*.yml`, not in the Databricks UI. Revert the change (A), then redeploy the same way as any change:

1. Through CI: the revert reaches `main`, `deploy.yml` deploys dev, then prod after approval.
2. By hand (needs the CLI and the target's principal credentials; the identity that deploys also owns and runs the job, so use the dev principal for dev and the prod principal for prod, never the admin): delete a local `.databricks` folder left by another identity, set `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` (and no `DATABRICKS_TOKEN`), then `databricks bundle deploy -t <dev|prod>`.
3. Check the job on its page in the Jobs UI (the owner column shows which principal's copy it is) and run it once.

A deploy keeps the job id and its history. **Drilled on dev:** the reverted code (`git diff` against the good commit printed nothing) was deployed as the dev principal in one command (`Files: 1 uploaded`, `Resources: 0 created, 0 changed, 0 deleted, 2 unchanged`) and the next run used it.

**Tables belong to the principal that created them**, and a schema owner does not get write access to them: for the `RESTORE` in B, an admin needs write rights on the schema first (the dev drill granted `ALL PRIVILEGES` and revoked it afterwards). On prod, grant it just for the repair and take it back.

## What a rollback cannot undo

- Files deleted from B2 or the HF archive (the archive job never deletes; B2 hides files after 270 days and keeps hidden files 30 days).
- A leaked secret: rotate it (re-key runbook for the HMAC key; revoke and recreate tokens).
- Anything already published (public site, releases), once those exist. The monthly release will get its own rollback note when P6 builds it.
- Time: a run that processed the wrong data has used its compute; the repair costs another run.

## Drill (2026-10-16, `p2_lakehouse/bootstrap/rollback_drill.py`)

**What was run:** sections A and B on scratch (production tables only read). A throwaway branch `rollback-drill-bad` carried a deliberate silent bug (13-digit codes labelled `gtin12`: no error, wrong data); `rollback-drill-fixed` was that branch plus a real `git revert` of it (its content was identical to `main`). Scratch input: the 4 newest real delta files (25,666 rows), 2 processed with the good code, then 2 with the bad code. Both drill branches were deleted afterwards.

**Result: PASS.**
- The bad run raised no error: it ended SUCCESS and wrote 13,173 rows whose `code_kind` differed from production. The runbook's premise (a bad run can pass quietly, so the data has to be checked, not only the job's status) is confirmed.
- A real `git revert` of the bad commit gave exactly the old code (no difference from `main`).
- B3: noting `DESCRIBE HISTORY` versions after the good run (silver rows 2, quarantine 1, manifest 2) and `RESTORE`-ing those three tables took 18 s and returned them exactly to "A only" (10,817 rows, 2 manifest rows, 0 wrong rows).
- B4/B5: rerunning with the reverted code on the same two files rebuilt them; the final 25,665 rows (plus 1 quarantine row) matched production exactly, with no duplicate keys and one balanced manifest row per file.

**Timings (each silver run includes about a minute of start-up):** good run 132 s, bad run 75 s, `RESTORE` of 3 tables 18 s, repair run 71 s.

**What the drill showed that the steps did not say:**
- Silver is insert-only, so rerunning fixed code over files the bad run already wrote changes nothing: the restore in B3 is not optional, it is what makes the repair run write the rows again. (This is why B3 lists the manifest among the tables to restore.)
- **The drill found a test gap.** Applied to a clean checkout, the same bug passed all 350 tests: no test asserted the 13-digit code kind (the most common barcode). A test over every real fixture code now fails with that bug and passes without it. A deliberate-bug drill is a cheap way to check that the tests would catch a silent data bug.

## Drill through the bundle (2026-10-16 night, dev target, `rollback-drill-bad`, local branch never pushed)

**What was run:** the same silent bug (13-digit codes labelled `gtin12`) committed on a local branch and deployed to dev with the CLI as the dev principal (`packsense-deployer-dev`). Dev silver was first restored to "file A only" (silver and manifest version 1, quarantine version 0); a copy of the good A+B silver (`drill_ref_good`, 13,638 rows) served as the reference. Production was not touched.

**Result: PASS.**
- The bad deploy ran the job to `SUCCESS` with `problems: 0` and wrote 6,523 rows with a wrong `code_kind` (of 13,638): the job's status shows nothing.
- `git revert` gave code identical to the good commit (`git diff` empty); a one-command redeploy as the dev principal shipped it (1 file uploaded, job unchanged).
- `RESTORE` of the three silver tables to the noted versions, then a run of the job: silver reprocessed file B (6,847 rows, 0 problems). Final comparison with the reference: 13,638 rows, 0 with a different `code_kind`, 2 manifest rows.

**What the drill showed:**
- Silver stays insert-only through the bundle too: the restore is required before the repaired code rewrites the rows.
- A revert is only live after a deploy; a plain revert on `main` changes nothing for the scheduled jobs until `deploy.yml` (and, for prod, the approval) runs.
- The admin needs write rights on the dev tables to run `RESTORE` (a principal-owned table).
- The `RESTORE` target versions are the ones noted before the bad run; they stay valid after later restores.

**Not exercised:** pausing the production schedule, section C (reverting a workflow, including `capture.yml`), section D (Terraform revert and apply, which needs the B2 admin key and the `terraform-apply` approval), a prod deploy of a revert (dev only), bronze repair (the same pattern with `bronze_delta_raw` and its manifest), and how far back production's own table history reaches.
