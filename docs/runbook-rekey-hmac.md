# Runbook: re-key the contributor HMAC (silver)

**Status: drilled on scratch 2026-10-16 (steps 2 to 6) and again 2026-10-18 with gold in mind (same steps plus the `distinct_editors` check); not drilled on production.** Written 2026-10-15 from the code (`silver_load.py`, `create_hmac_key.py`, `contracts/silver.yml`), then drilled twice on a scratch copy of 6 real delta files: see "Drill" below for what passed, what the drills corrected, and what they did not cover (pausing the schedule is replaced by a time window; the production drop, the gold re-grant and the manual gold build were not executed). Re-drill after any change to silver.

## What the key does

Silver replaces each contributor username with `HMAC-SHA256(key, normalised name)` (10 `egress: never` columns). The key is the 32-byte hex secret `hmac_key_v1` in Databricks secret scope `packsense`. There is deliberately **no escrow copy and no GitHub copy**: bronze and the HF archive keep the raw names, so the codes can always be rebuilt.

## When to use this

| Situation | Action |
|---|---|
| Key lost (secret deleted, scope lost, workspace lost) | Re-key (this runbook), because the old codes cannot be reproduced |
| Key suspected leaked | Re-key. Note that OFF publishes the usernames, so a leaked key lets anyone re-identify contributors by hashing the public list; the old codes are exposed as well |
| Routine rotation | Same steps; no calendar schedule is set |

What does **not** need a re-key: a leaked Databricks token (rotate the token), a healthchecks URL (regenerate it).

## What a re-key changes

- Every contributor gets a **new code**. Codes from before and after are not comparable.
- **Gold carries no code** (amendment A29): the only value it derives from the codes is `distinct_editors`, a count of distinct codes per period, and no gold table needs a rebuild because of new codes. A count of distinct names does not change when every name gets a new code, and the 2026-10-18 drill checked that row by row on real data (see "Drill" below). The ML features and the review store do not exist yet; when they do and carry a code, extend this section.
- **But gold READS silver, which creates two hazards in the middle of a re-key:** (a) while silver is being rebuilt it is partial, and gold rebuilds its tables in full from silver, so a gold build in that window would overwrite them with partial data until the next good run (the warn test `history_not_below_status` would notice, but the tables would still be wrong); (b) dropping `silver_product_versions` and `silver_manifest` removes the gold principals' table-level `SELECT`, so the next gold run fails on a permission error until they are re-granted (a failure that is loud, not silent).
- Silver is **rebuilt from bronze** (about 8 minutes for the 27 files and 114,259 rows measured on 2026-10-15; silver on 22,342 seed rows took 129 s, the 14 daily files 308 s).
- Silver writes are insert-only (`MERGE ... WHEN NOT MATCHED THEN INSERT`), so existing rows are **never updated**: a new key without a rebuild would leave old codes in place and mix the two. The rebuild is therefore mandatory, not optional.

## Steps

0. **Record the baseline** (for step 6): silver, quarantine and manifest row counts, bronze row count, and from gold the rows of `product_history`, `product_flag_spans` and the sum of `n_products` in `mart_brand_scorecard` (read-only counts).
1. **Choose a window instead of pausing** (corrected 2026-10-18; the old text said to pause the schedule in the UI). A bundle job has no pause control in the Jobs UI, and a deploy resets the schedule anyway (A28), so use a time window with a hard stop, as the table-swap runbook does. The jobs that read or write silver are `packsense-bronze-load` (09:00 UTC) and `packsense-gold-build` (09:30 UTC, about 4 min); `packsense-archive` (16:00 UTC) reads B2 only and is unaffected. Start after the gold run has finished (about 09:40 UTC), finish steps 5 to 7 before the next 09:00 UTC, and do not deploy anything in between. A manual run of `packsense-bronze-load` also pings healthchecks; the core check stays green if it runs within its 1 d / 3 h period.
2. **Create the new key** `hmac_key_v2` (hex, 32 random bytes). `create_hmac_key.py create` is hard-wired to `hmac_key_v1`: change `SECRET` to `hmac_key_v2` on a branch (the script refuses to overwrite an existing secret, so it cannot touch v1), run `create`, and keep the printed non-secret **key-check value** in the build log. If the old key was only suspected leaked, delete `hmac_key_v1` from the scope after step 6, not before.
3. **Edit the contract** on a branch: in `p2_lakehouse/contracts/silver.yml` set `hmac.secret_key: hmac_key_v2` and `hmac.key_version: 2`, and update the tests that pin version 1 (`test_transform.py` asserts `hmac_key_version == 1`; `test_bootstrap_secret.py` already accepts `hmac_key_v2`). Every rebuilt row then carries `hmac_key_version = 2`.
4. **Rebuild silver in a scratch schema first** (the verification pattern used for contract v2 and v3): run `silver_load.py` with the `silver_schema` widget pointing at a scratch schema and `ping_healthchecks=false`. Check: rows equal the production silver counts for the same files (114,257 silver + 2 quarantine at the last count), no duplicate `(code, last_modified_t)`, every row has `hmac_key_version = 2`, and none of the 10 code columns has a **non-empty** code equal to the old code for the same product (an empty list of codes is the same under any key, so it is not a failure). Drop the scratch schema.
5. **Swap in production.** Merge the branch to `main` (fast-forward), then drop the derived tables and let the job rebuild them: `silver_product_versions`, `silver_quarantine` and `silver_manifest` in `workspace.packsense_silver`. `silver_manifest` must go too, otherwise silver considers every file done and processes nothing. Keep `silver_run_stats`, `silver_field_log` and `silver_drift_report` (they hold no codes; the drift baseline is read from them). Run `packsense-bronze-load` once by hand (bronze loads 0 files, silver processes all of them; about 8 minutes for the 128,598 rows of the 2026-10-17 swap, so allow 10 minutes plus job start). **Then re-grant the gold principal** (the dropped tables took its grants with them): ``GRANT SELECT ON TABLE workspace.packsense_silver.silver_product_versions TO `520fb1ac-a6cf-4913-b7af-c081eb32456c`;`` and the same for `silver_manifest` (the client id is `packsense-gold`; `silver_taxonomy_tag` is not dropped and keeps its grant). Check with `SHOW GRANTS ON TABLE workspace.packsense_silver.silver_product_versions`. The dev gold principal is not touched: dev silver has its own throwaway key.
6. **Verify production:** silver and quarantine counts equal the figures from before the drop; manifests 27 of 27 (or the current count); lineage joins to bronze 1:1; the drift task is quiet (it compares shares and does not see the codes). **Then rebuild gold by hand once** (`python p4_modelling/bootstrap/run_gold_prod.py --env-file .env` from the repo root: it starts the production job with the admin token and the job runs as `packsense-gold`; after the re-grant) and compare with the step 0 baseline: `product_history`, `product_flag_spans` and the scorecard product count must be identical, because gold derives nothing from the codes except the unchanged `distinct_editors`; a gold run that fails with a permission error means the re-grant was missed. Then, if the old key was compromised, delete `hmac_key_v1` from the scope.
7. **Resume the schedule** and record the date, the timings and the new key-check value in the build log and worklog.

**Gold exists (extended 2026-10-18).** No gold table carries a code, so there is nothing in gold to rebuild; the extension is the window, the re-grant and the check of gold afterwards (steps 0, 1, 5 and 6). **Not drilled:** the drop of production silver, the loss and re-grant of the gold principal's grants, and the manual production gold build, because drilling them means dropping production silver. The invariance of `distinct_editors` was drilled on scratch.

## Rollback

Until `hmac_key_v1` is deleted (step 6) the old state is recoverable: revert the contract commit and rebuild with v1. After deletion, rollback means another re-key.

## Drill checklist (do once, then tick)

- [ ] Steps 2 to 4 on a scratch schema, with timings
- [ ] Confirm `create_hmac_key.py` change for v2 works without touching v1
- [ ] Confirm no other test or code pins the key name or version (only the two test files above were found by search)
- [ ] Update this runbook with the real timings and anything that differed

## Drill (2026-10-16, `p2_lakehouse/bootstrap/rekey_drill.py`)

**What was run:** steps 2 to 6 on scratch (steps 1 and 7 are UI actions; the production drop and run of step 5 were done on a scratch silver schema instead, with the same three tables dropped). The throwaway key was created with the runbook's own method (`create_hmac_key.py create` with `SECRET` changed on a branch), read back inside Databricks (key-check matched), and deleted afterwards. Scratch input: 6 real delta files (40,253 rows) including both files that hold quarantined rows. Production tables were only read.

**Result: PASS** (second run). Silver built with `hmac_key_v1`, the three derived tables dropped, rebuilt with `hmac_key_v2`: row counts equal (40,251 silver + 2 quarantine), no duplicate keys, every row carries `hmac_key_version = 2`, all 56 columns that must not change identical, no non-empty code kept its old value in any of the 10 columns, the 2 quarantine payloads changed with the key (they carry hashed identities), one balanced manifest row per file.

**Timings:** silver with v1 142 s, rebuild with v2 135 s (a first run took 199 and 142 s), each including about a minute of job start-up. Extrapolated, not measured: the full production silver (122,258 rows, 28 files at the time) should take roughly 5 to 8 minutes, in line with the earlier measured full runs (308 s for 91,917 rows).

**What the drill corrected:**
- Step 3's claim holds: only the contract's `secret_key` and `key_version`, `SECRET` in the key script and the version-1 pin in `test_transform.py` needed editing; all 350 tests then passed, so no other test depends on the key version.
- Step 4/6 verification said no code column may equal the old code. That is wrong for the array columns: an empty list stays empty under any key, and `checkers_hmac` (about 99.5% empty) and `weighers_hmac` (about 98%) are mostly empty. The first drill run reported them as failures for that reason; the check now compares non-empty codes only.

**What the drill did not cover:** pausing the production schedule, dropping and rebuilding the production tables, the real cutover timing against the 09:00 UTC job, the healthchecks behaviour during a long run, and anything downstream of silver (nothing carries a code yet; gold will).

**How to repeat it:** the procedure is in the header of `rekey_drill.py`. Never leave `hmac_key_v2` in the scope after a drill: a real re-key refuses to start if it already exists.

## Second drill (2026-10-18, gold in mind)
Same script and method (`rekey_drill.py run`, then `cleanup` and `delete-secret --yes`), run from a separate git worktree so the working tree and branch were untouched; the throwaway `hmac_key_v2` (key-check `9804bf88`, non-secret) was created with `create_hmac_key.py create` on a branch with the three step 3 edits, and deleted afterwards (the scope again holds only `hmac_key_v1` and the six other secrets; 0 scratch schemas left; the drill branch was never merged and is deleted). Scratch input: 6 real delta files (39,905 bronze rows, both quarantine files). **Result: PASS.** Silver v1 39,903 + 2 quarantine, rebuild with v2 39,903 + 2; no duplicate keys; every row `hmac_key_version = 2`; the 66 columns that must not change are identical; no non-empty code kept its old value; one balanced manifest row per file. **New check: `distinct_editors` (`coalesce(size(array_distinct(editors_hmac)), 0)`, the only value gold derives from the codes) is identical under both keys on every one of the 39,903 rows, and every row has at least one editor, so the check is not vacuous.** That supports the runbook's claim that no gold table changes in a re-key (the claim is about those counts; gold was not built from the scratch silver). Timings: silver v1 206 s, rebuild with v2 154 s, each with about a minute of job start-up.
**Still not covered:** dropping and rebuilding the PRODUCTION silver, the loss of the gold principal's grants on the dropped tables and their re-grant, and a production gold build afterwards. Those steps follow the table-swap runbook's re-grant (9b) and the A29 grants and are written, not drilled.
