# Runbook: re-key the contributor HMAC (silver)

**Status: written 2026-10-15, not yet drilled.** Every step below is read from the code (`silver_load.py`, `create_hmac_key.py`, `contracts/silver.yml`) and not yet executed end to end. Run the drill once on a scratch schema before relying on it, and record the timings here.

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
- Nothing downstream depends on the codes yet (gold, dbt and the ML features do not exist). Once gold exists, this runbook must also rebuild every table that carries or joins on a code; update it then.
- Silver is **rebuilt from bronze** (about 8 minutes for the 27 files and 114,259 rows measured on 2026-10-15; silver on 22,342 seed rows took 129 s, the 14 daily files 308 s).
- Silver writes are insert-only (`MERGE ... WHEN NOT MATCHED THEN INSERT`), so existing rows are **never updated**: a new key without a rebuild would leave old codes in place and mix the two. The rebuild is therefore mandatory, not optional.

## Steps

1. **Pause the daily job** so nothing writes during the rebuild: pause the schedule of `packsense-bronze-load` in the Databricks UI (`create_bronze_job.py` has no pause command: its `schedule` subcommand only attaches an unpaused schedule). A manual run of `packsense-bronze-load` also pings healthchecks; expect the core check to be late, not red, if this takes under its 3 h grace.
2. **Create the new key** `hmac_key_v2` (hex, 32 random bytes). `create_hmac_key.py create` is hard-wired to `hmac_key_v1`: change `SECRET` to `hmac_key_v2` on a branch (the script refuses to overwrite an existing secret, so it cannot touch v1), run `create`, and keep the printed non-secret **key-check value** in the build log. If the old key was only suspected leaked, delete `hmac_key_v1` from the scope after step 6, not before.
3. **Edit the contract** on a branch: in `p2_lakehouse/contracts/silver.yml` set `hmac.secret_key: hmac_key_v2` and `hmac.key_version: 2`, and update the tests that pin version 1 (`test_transform.py` asserts `hmac_key_version == 1`; `test_bootstrap_secret.py` already accepts `hmac_key_v2`). Every rebuilt row then carries `hmac_key_version = 2`.
4. **Rebuild silver in a scratch schema first** (the verification pattern used for contract v2 and v3): run `silver_load.py` with the `silver_schema` widget pointing at a scratch schema and `ping_healthchecks=false`. Check: rows equal the production silver counts for the same files (114,257 silver + 2 quarantine at the last count), no duplicate `(code, last_modified_t)`, every row has `hmac_key_version = 2`, and none of the 10 code columns equals the old code for the same product. Drop the scratch schema.
5. **Swap in production.** Merge the branch to `main` (fast-forward), then drop the derived tables and let the job rebuild them: `silver_product_versions`, `silver_quarantine` and `silver_manifest` in `workspace.packsense_silver`. `silver_manifest` must go too, otherwise silver considers every file done and processes nothing. Keep `silver_run_stats`, `silver_field_log` and `silver_drift_report` (they hold no codes; the drift baseline is read from them). Run `packsense-bronze-load` once by hand (bronze loads 0 files, silver processes all of them).
6. **Verify production:** silver and quarantine counts equal the figures from before the drop; manifests 27 of 27 (or the current count); lineage joins to bronze 1:1; the drift task is quiet (it compares shares and does not see the codes). Then, if the old key was compromised, delete `hmac_key_v1` from the scope.
7. **Resume the schedule** and record the date, the timings and the new key-check value in the build log and worklog.

**When gold exists (P4) this runbook must be extended** to rebuild every table that carries or joins on a code, and that extension must be drilled too.

## Rollback

Until `hmac_key_v1` is deleted (step 6) the old state is recoverable: revert the contract commit and rebuild with v1. After deletion, rollback means another re-key.

## Drill checklist (do once, then tick)

- [ ] Steps 2 to 4 on a scratch schema, with timings
- [ ] Confirm `create_hmac_key.py` change for v2 works without touching v1
- [ ] Confirm no other test or code pins the key name or version (only the two test files above were found by search)
- [ ] Update this runbook with the real timings and anything that differed
