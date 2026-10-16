# Runbook: swap the silver tables for a new contract version (first used for v3 to v4, 2026-10-17)

**Status: DRAFT. Not yet drilled; the dev rehearsal comes first and this file is corrected from what it finds.**

## When this is needed
Silver is insert-only and its tables are created from the contract (`CREATE TABLE IF NOT EXISTS`). A contract that adds, removes or
retypes a column therefore cannot run against the existing table: the first run after the new code is deployed would fail on the
column mismatch. The table has to be replaced by one built from bronze. (A change that only adds a rule without touching the column list
does not need a swap; rows written earlier simply keep the old rule until a rebuild.) The rebuild is deterministic: the same bronze
and the same key give the same rows, which is what makes the comparison below possible.

## What is swapped and what is kept
| Table | Action | Why |
|---|---|---|
| `silver_product_versions`, `silver_quarantine`, `silver_manifest` | rename to `..._v3`, new ones are built | the new contract's columns; the manifest empty makes silver process every bronze file |
| `silver_drift_metrics` | rename to `..._v3` | the layer-3 counts were measured under the old rules; without this the first day after the swap alerts on columns with no history. The drift task re-measures every delta day under the new rules |
| `silver_drift_report` | keep | days already judged stay judged, so nothing re-alerts |
| `silver_run_stats`, `silver_field_log` | keep | history only; the field log feeds the new-field-family check |

The old tables stay as the rollback until the new ones have been through at least one scheduled day; they are dropped afterwards on purpose.

## Preconditions (check all before step 1)
1. The new contract and code are on a branch that passed `tests` and `lint`; **do not merge to `main` yet** if `main` deploys to the target (a
   merge starts `deploy.yml`: dev by itself, prod waiting for approval).
2. A scratch rebuild of ALL of bronze was compared with the current tables: `p2_lakehouse/bootstrap/silver_v4_check.py run` (PASS). For v4 this
   was done on 2026-10-17.
3. No run of the job is in progress and none is due within the next hour; the scheduled run of the day has finished and was green.
4. For prod: the person doing it can approve the `prod` environment and has the admin SQL editor open.

## Steps (target = dev or prod; names below are for prod, dev uses the `packsense_dev_*` schemas)
1. **Pause the job.** Prod: pause the schedule of `packsense-bronze-load` in the Jobs UI (the bundle-owned job). Dev: schedules are already paused.
2. **Give the admin the right to rename and drop** (tables belong to the principal that created them, a schema owner does not get access):
   `GRANT ALL PRIVILEGES ON SCHEMA <silver schema> TO <admin user>`. Revoke it at the end and restore the standing `SELECT`.
3. **Note the state to return to:** row counts of the three tables and the manifest file list (`SELECT file_name FROM silver_manifest`).
4. **Rename the old tables** (admin, SQL editor), one statement each:
   `ALTER TABLE <silver schema>.silver_product_versions RENAME TO silver_product_versions_v3;` and the same for `silver_quarantine`,
   `silver_manifest` and `silver_drift_metrics`.
5. **Ship the new code.** Dev: `databricks bundle deploy -t dev` from the branch as the dev principal (delete a local `.databricks` folder left
   by another identity first). Prod: merge the branch to `main` through CI; `deploy.yml` deploys dev, then approve the `prod` environment.
   Confirm the deploy output says what was uploaded before going on.
6. **Run the job once by hand** (dev: `databricks bundle run bronze_load -t dev`; prod: Run now in the Jobs UI on the bundle-owned job). Bronze loads
   nothing new, silver creates the new tables and processes every file, drift measures every delta day. Expect about 8 to 9 minutes for the full data.
7. **Verify against the renamed tables** (same tool as the scratch check, nothing is rebuilt):
   `python p2_lakehouse/bootstrap/silver_v4_check.py run --env-file .env --silver-schema <silver schema> --bronze-schema <bronze schema> --old-suffix _v3`.
   It must end `RESULT: PASS`: balance, keys, every old column identical (except what the contract change says), new columns against bronze,
   residue, lineage. Then run the drift check once more and read its report.
8. **Resume the schedule** (prod) and watch the next scheduled run and its healthchecks; the drift check may be red only for alerts that are
   real (see the drift gotchas in the buildlog).
9. **Revoke the temporary admin rights** from step 2.
10. **After one clean scheduled day**, drop the four `_v3` tables. Until then they are the rollback.

## Rollback (if step 6 or 7 fails, or a scheduled day after the swap is wrong)
1. Pause the job.
2. Admin: drop the new tables (`silver_product_versions`, `silver_quarantine`, `silver_manifest`, `silver_drift_metrics`), then rename each `_v3` table back.
3. Put the old code back: revert the change on `main` (`git revert`, CI, deploy; see `runbook-rollback.md` section E), or for dev `bundle deploy` from the previous commit.
4. Run the job once: it must find the manifest complete (0 files) and end green; compare the counts with step 3.
5. Resume the schedule.

## Findings from the dev rehearsal
(to be filled in)
