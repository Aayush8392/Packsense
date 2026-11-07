# Failure modes: what was tried, what happened, how to recover

One row per failure that was actually made to happen. Rows marked "not run" say so. Dates are the day the drill ran.

## Drills that were run

| Failure mode | What was observed | Recovery | Drill |
|---|---|---|---|
| Bronze run killed mid-write (cancelled while merging) | Killed in the risky window (rows written, no manifest row) in 2 of 3 trials; the third finished during the cancel and does not count. | Re-run the same notebook. Files with a manifest row are skipped, the others load again. Recovered tables matched production: no duplicate keys, one manifest row per file. | `p2_lakehouse/bootstrap/crash_test.py bronze`, 2026-10-15 |
| Silver run killed mid-write | Two rounds of 3 trials: in each round one kill landed with rows written and no manifest row, the others between files. | Re-run. The recovered silver and quarantine tables matched production row for row. | `crash_test.py silver`, 2026-10-15 and 2026-10-16 |
| Crash between the silver write and the quarantine write (a window of a few seconds, too short to aim at) | The crash STATE was built by hand (quarantine rows and manifest rows deleted); the recovery run is real. | Re-run silver: identical to production. | `crash_test.py window`, 2026-10-16 |
| Daily capture fails | The failure was forced with `drill_fail` and the capture reported it. | Capture again; landing is keyed by file name and checksum, so a re-run is harmless, and a skipped day is caught up inside OFF's 14-day window. | manual run 674969610285938 (session 15) |
| A day of raw data lost from landing and bronze | One delta restored from the Hugging Face archive (no B2); sha256 equal three ways; real bronze and silver on scratch schemas matched production. | `p2_lakehouse/bootstrap/restore_drill.py` | A4 b, 2026-10-19 |
| Principal secrets expire or leak | The four principal OAuth secrets were rotated by one command and the jobs kept running. | `docs/runbook-secret-rotation.md` | A1, run live 2026-10-19 |
| Processing stops for 3 days while capture keeps landing files | One catch-up pass over the 3 landed days gave exactly what 3 daily runs gave (19,581 bronze rows, 19,581 silver rows, 0 quarantine, manifest counts equal). A second pass loaded 0 files and changed nothing. Production unchanged; no scratch left. | Run bronze and silver once; no special step. | `p2_lakehouse/bootstrap/outage_drill.py run --days 3`, 2026-11-07. Notebook time 296 s over 6 runs. |
| Processing stops for 10 days | Same result over 69,232 rows (silver 69,232, quarantine 0). Second pass loaded 0 files. | Same. | `outage_drill.py run --days 10`, 2026-11-07. Notebook time 463 s over 6 runs. |
| Landing lost: the oldest days exist only in the Hugging Face archive | The 8 days that production had loaded but landing no longer held (the oldest, 8.0 days, no gaps) were fetched from the archive; all 8 matched in sha256 three ways (restored copy, archive manifest, the hash the capture recorded). One pass of the real bronze and silver gave 55,877 bronze rows, 55,876 silver rows and 1 quarantine row, identical to production. A second pass loaded 0 files. Production unchanged; no scratch left. | Fetch the files from the archive into landing, then run bronze and silver once; no special step. | `p2_lakehouse/bootstrap/rebuild_drill.py run`, 2026-11-07. Notebook time 444 s over 6 runs (fetch 105 s). Not covered: the seed load (from the dump repo), and days still in landing. |
| Archive job cancelled while archiving | Scratch repo, 6 files, one file per batch. Four earlier cancels missed the archiving loop (it is about 15 s of a 66 s run and a cancel takes 19 to 34 s to take effect): they landed before the first batch or after the last manifest write, and both were handled correctly (re-run archived all 6, or 0). The fifth landed between batches: manifest recorded 5, repo stored the same 5, every hash equal to the real archive. The re-run archived exactly the 1 missing file (19.4 MB) and ended green. Real archive only read. | Re-run the job: only files without a manifest row are archived again. | `p1_intake/bootstrap/archive_kill_drill.py run`, 2026-11-07. One cancel landed mid-run; the window between an upload and its manifest write (a few seconds) was not hit. |

Cost of the drills, measured from `system.billing.usage` for the drills' own notebook runs (the SQL warehouse is a separate item and was not counted): 3-day outage 1.532 DBU (296 s), 10-day outage 1.807 DBU (463 s). Cost barely grows with rows: most of it is the fixed cost of six serverless runs. Rebuild and archive-kill DBU: not read yet (billing lags by hours).

## Drills not run

| Failure mode | Status |
|---|---|
| Processing stops for 20 days | Not run, by decision (2026-11-07). The 3-day and 10-day runs prove the property; a 20-day run uses the same code on more rows. Forecast from the two measured points: about 12 minutes of notebook time, worst case about an hour. |
| Terraform state lost or damaged | Planned, not run. |

## What the outage drills do not cover

- They copy landed files inside Databricks; they do not stop the real scheduled jobs, so they do not test the scheduler or the healthchecks alarm for a stopped job.
- The comparison is with production's own result for the same files, so a bug that production and the drill share would not show.
- Cancelled runs only, as in the kill tests: a lost node or a cut network was not simulated.
