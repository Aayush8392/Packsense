# Runbook: swap the silver tables for a new contract version (first used for v3 to v4, 2026-10-17)

**Status: drilled on the dev target on 2026-10-17 (swap, in-place verification and rollback, all PASS) and carried out on production the same night (v3 to v4, PASS, see the end).** The statements below are the corrected ones: the rehearsal found four problems, listed at the end.

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
1. **Keep a scheduled run from landing in the middle.** A job deployed from the bundle cannot be paused in the Jobs UI (there was no pause control on 2026-10-17;
   inferred cause: bundle jobs are locked against UI edits), and `bundle deploy` sets the schedule back to what the bundle file says anyway, so a pause would not survive
   step 5. Instead choose a window: start at least 4 hours before the next scheduled run (06:45 UTC since 2026-10-18; it was 09:00 UTC when this was drilled), do the renames and the deploy back to back, and set a hard stop (07:30 UTC)
   after which you roll back. Dev: schedules are already paused.
2. **Give the admin the right to rename and drop** (tables belong to the principal that created them, a schema owner does not get access):
   `GRANT ALL PRIVILEGES ON SCHEMA <silver schema> TO <admin user>`. Revoke it at the end (step 9).
3. **Note the state to return to:** row counts of the three tables and the manifest file list (`SELECT file_name FROM silver_manifest`).
4. **Rename the old tables** (admin, SQL editor), one statement each, **with the new name fully qualified**:
   `ALTER TABLE <silver schema>.silver_product_versions RENAME TO <silver schema>.silver_product_versions_v3;` and the same for `silver_quarantine`,
   `silver_manifest` and `silver_drift_metrics`. An unqualified new name is resolved against the SQL editor's current schema, so the table lands in
   `workspace.default` (seen in the rehearsal), where the admin has no rights and cannot move it back without first granting itself the schema.
   **Then list the schema and confirm all four `_v3` tables exist and the four originals are gone** (`SELECT table_name FROM workspace.information_schema.tables
   WHERE table_schema = '<schema name>' ORDER BY table_name`): in the rehearsal one rename silently did not apply. A rename keeps the owner (the principal).
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
9. **Revoke the temporary admin rights** from step 2 and restore the standing read access:
   `REVOKE ALL PRIVILEGES ON SCHEMA <silver schema> FROM <admin user>;` then `GRANT SELECT ON SCHEMA <silver schema> TO <admin user>;`.
9b. **Re-grant the gold principals** (added after the gold layer existed). They hold table-level `SELECT` on `silver_product_versions`, `silver_manifest` and `silver_taxonomy_tag` only (a product-contract swap renames the first two and not the taxonomy table). The grants are in `p5_governance/grants.yml`.
   Whether a rename keeps a table's grants is not verified: after the swap run `python p5_governance/bootstrap/apply_grants.py plan --env-file .env` (an admin): a lost table grant shows as MISSING, and `apply` puts it back
   (it only adds). Gold fails on a missing grant, not silently.
9c. **Re-attach the masks** (P5 step 4). The ten hashed contributor columns of `silver_product_versions` are masked through `p5_governance/policies.yml`. A rename keeps a mask on the OLD table (it becomes `_v3`) and the new table the job creates has none, so run
   `python p5_governance/bootstrap/apply_policies.py plan --env-file .env` (a missing mask shows as MASK ... live None) and then `apply --only prod` (or `dev`). Until then the new table is unmasked (nobody but the exempt principals can read it, so nothing leaks, but the nightly policies check is red).
10. **After one clean scheduled day**, drop the four `_v3` tables. Until then they are the rollback.

## Rollback (if step 6 or 7 fails, or a scheduled day after the swap is wrong)
1. Pause the job.
2. Admin (with the rights from step 2): drop the new tables (`silver_product_versions`, `silver_quarantine`, `silver_manifest`, `silver_drift_metrics`), then rename each
   `_v3` table back, again with the fully qualified new name.
3. Put the old code back: revert the change on `main` (`git revert`, CI, deploy; see `runbook-rollback.md` section E), or for dev `bundle deploy` from the previous commit.
4. Run the job once: it must find the manifest complete (0 files processed) and end green; compare the counts and the column count (71 for v3) with step 3.
5. Resume the schedule.

## Findings from the dev rehearsal (2026-10-17, dev target, v3 to v4 and back)
**Result: PASS both ways.** Forward: after the renames and a deploy of the v4 branch as the dev principal, one run of the job rebuilt silver from bronze (2 files, 13,638 rows, 0 problems, about
2 minutes); the in-place check ended `RESULT: PASS` (balance, keys, lineage, 71 old columns identical on every row except one `traces_tags` row changed by the digit-run rule, all ten new
columns equal to bronze's raw JSON, no residue). Back: dropping the v4 tables, renaming the `_v3` tables back and deploying `main`'s code left 13,638 silver rows, 2 manifest rows and 71 columns; the
next run processed 0 files and ended green.

**What the rehearsal found that the first draft got wrong:**
1. `RENAME TO` with an unqualified new name puts the table into the editor's current schema (`workspace.default`), not the table's own schema. Use fully qualified names.
2. A table the principal created stays the principal's after a rename; once it sat in `workspace.default` the admin had no rights on it (`PERMISSION_DENIED: does not have MODIFY and SELECT`), and
   had to grant itself `ALL PRIVILEGES` on that schema before moving it back. Rights come from the schema, so a backup table must stay in the schema whose grants cover it.
3. One of the four renames printed OK but did not apply (the quarantine table kept its original create date); only the table list showed it. Always list the schema after the renames.
4. In dev the quarantine table was empty. In production it holds 2 rows (both the empty barcode): the rebuild writes them again, so the quarantine table must be swapped with the others
   (as step 4 says) and not kept.

**Not exercised on dev:** the production deploy approval path in this order (the dev deploy was by CLI), and a swap with quarantined rows (covered by the scratch full-data run and then by production).

## Production swap, v3 to v4 (2026-10-17, about 02:00 to 02:45 IST)
Baseline before: 128,596 silver rows, 2 quarantine rows, 29 manifest rows, 80 drift-metric rows, 128,598 bronze rows. Steps as above, with these differences from the draft: no pause (see step 1);
the push of `main` to start `deploy.yml` was refused to the assistant by the permission classifier and run by the user; the four renames were applied and listed correctly the first time (qualified names).
The prod deploy was approved after the renames (deploy run #3), then the bundle-owned job was run by hand: bronze 22 s, silver 7 m 55 s, drift 3 m 10 s, all green (11 m 30 s in total).
**Verification (`silver_v4_check.py run --silver-schema workspace.packsense_silver --bronze-schema workspace.packsense_bronze --old-suffix _v3`): PASS, identical to the scratch rebuild:** 128,596 silver + 2
quarantine = 128,598 bronze; same keys; 67 old columns identical on every row except the 2 old-format delta rows (13 nutrition columns) and the digit-rule changes (categories 7 rows, labels 20, traces 10);
ten new columns equal to bronze's raw JSON; no residue; every row contract version 4. The `_v3` tables stay until one clean scheduled day has passed.
