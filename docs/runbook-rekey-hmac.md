# Runbook: re-key the contributor HMAC (silver)

**Status: drilled on scratch 2026-10-16 (steps 2 to 6; not on production).** Written 2026-10-15 from the code (`silver_load.py`, `create_hmac_key.py`, `contracts/silver.yml`), then drilled once on a scratch copy of 6 real delta files: see "Drill" below for what passed, what the drill corrected, and what it did not cover (pausing the schedule and the production swap were not executed). Re-drill after any change to silver, and extend both the runbook and the drill when gold exists.

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
4. **Rebuild silver in a scratch schema first** (the verification pattern used for contract v2 and v3): run `silver_load.py` with the `silver_schema` widget pointing at a scratch schema and `ping_healthchecks=false`. Check: rows equal the production silver counts for the same files (114,257 silver + 2 quarantine at the last count), no duplicate `(code, last_modified_t)`, every row has `hmac_key_version = 2`, and none of the 10 code columns has a **non-empty** code equal to the old code for the same product (an empty list of codes is the same under any key, so it is not a failure). Drop the scratch schema.
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

## Drill (2026-10-16, `p2_lakehouse/bootstrap/rekey_drill.py`)

**What was run:** steps 2 to 6 on scratch (steps 1 and 7 are UI actions; the production drop and run of step 5 were done on a scratch silver schema instead, with the same three tables dropped). The throwaway key was created with the runbook's own method (`create_hmac_key.py create` with `SECRET` changed on a branch), read back inside Databricks (key-check matched), and deleted afterwards. Scratch input: 6 real delta files (40,253 rows) including both files that hold quarantined rows. Production tables were only read.

**Result: PASS** (second run). Silver built with `hmac_key_v1`, the three derived tables dropped, rebuilt with `hmac_key_v2`: row counts equal (40,251 silver + 2 quarantine), no duplicate keys, every row carries `hmac_key_version = 2`, all 56 columns that must not change identical, no non-empty code kept its old value in any of the 10 columns, the 2 quarantine payloads changed with the key (they carry hashed identities), one balanced manifest row per file.

**Timings:** silver with v1 142 s, rebuild with v2 135 s (a first run took 199 and 142 s), each including about a minute of job start-up. Extrapolated, not measured: the full production silver (122,258 rows, 28 files at the time) should take roughly 5 to 8 minutes, in line with the earlier measured full runs (308 s for 91,917 rows).

**What the drill corrected:**
- Step 3's claim holds: only the contract's `secret_key` and `key_version`, `SECRET` in the key script and the version-1 pin in `test_transform.py` needed editing; all 350 tests then passed, so no other test depends on the key version.
- Step 4/6 verification said no code column may equal the old code. That is wrong for the array columns: an empty list stays empty under any key, and `checkers_hmac` (about 99.5% empty) and `weighers_hmac` (about 98%) are mostly empty. The first drill run reported them as failures for that reason; the check now compares non-empty codes only.

**What the drill did not cover:** pausing the production schedule, dropping and rebuilding the production tables, the real cutover timing against the 09:00 UTC job, the healthchecks behaviour during a long run, and anything downstream of silver (nothing carries a code yet; gold will).

**How to repeat it:** the procedure is in the header of `rekey_drill.py`. Never leave `hmac_key_v2` in the scope after a drill: a real re-key refuses to start if it already exists.
