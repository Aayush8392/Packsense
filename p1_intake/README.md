# P1 — Intake

Gets Open Food Facts data into the platform every day and proves it arrived: the daily delta capture, the landing volume,
taxonomy snapshots and the tripwires that watch them. Runs entirely on GitHub Actions and Databricks; no laptop in the chain.

| File | What it does |
|---|---|
| `capture_deltas.py` | Downloads every OFF delta file not yet landed, checks it, uploads to B2 (upload-only key) and the landing volume, writes a manifest. Recovers orphaned landing files (landed, but in no manifest). Workflow: `.github/workflows/capture.yml` (07:30 UTC). |
| `capture_taxonomies.py` | Snapshots 34 OFF taxonomies, stored only when they change, plus a daily log of the version in force. Same workflow, second step. |
| `check_freshness.py` | Tripwire: is the newest OFF delta in landing? Workflow: `.github/workflows/freshness.yml` (11:00 UTC), alerts through healthchecks.io. |
| `check_delete_markers.py` | Tripwire: has anything hidden an object in the capture bucket (an upload-only B2 key can hide objects)? Lifecycle-aware; workflow `.github/workflows/delete-markers.yml` (11:30 UTC) with a `self_test` input that makes a real marker to prove the alert. |
| `archive_lib.py`, `notebooks/archive_to_hf.py` (the job itself is defined in `p3_delivery/resources/archive_job.yml`; the old `create_archive_job.py` script was removed on 2026-10-17) | The archive job: every object in B2 (`raw/`, `taxonomies/`) is copied to a private Hugging Face dataset, each file checked (size, B2's checksum, gzip complete, the capture's recorded sha256) and compared with what Hugging Face reports storing; the archive manifest is written last. Daily Databricks job at 16:00 UTC. It never deletes from B2. A setup crash is reported to healthchecks as a failure. |
| `retention_lib.py`, `notebooks/landing_retention.py` | Landing retention, the second task of the archive job (runs only if the archive succeeded). A landed delta file is deleted only if it is older than 30 days (by the end time in its name; OFF keeps about 14 days listed, and the capture decides what to fetch from what is in landing), bronze loaded it, and the Hugging Face archive holds the same sha256. At most 20 deletions per run, a dry-run switch, never touches manifests or taxonomy snapshots. After 30 days a rebuild reads the HF archive, not landing. Failures ping the archive healthcheck as `/fail`. |
| `reconcile_lib.py`, `notebooks/b2_reconcile.py` | B2 reconciliation, the third task of the archive job (after the archive, even if it failed): does the bucket hold exactly what the records say? It lists B2 (never downloads, so the free daily download cap is untouched) and compares it with the capture manifests, taxonomy logs and snapshots (recorded size, or the landing copy's size), the landed delta files and the Hugging Face archive manifest; it flags missing objects, size differences, objects nobody recorded, files older than 36 h that are not archived and archived keys gone from B2 inside the 270-day window. Checks existence and size, not content (content was checked at capture and archive); taxonomy snapshots are compared with their landing copy. Findings ping the archive healthcheck as `/fail`. |
| `check_secret_expiry.py` | Tripwire: is any credential within 10 days of expiring? Daily workflow `.github/workflows/secret-expiry.yml` (08:00 UTC; a manual run takes a `threshold_days` input). The list of secrets and expiry dates is deliberately **not in this public repository**: it is a repository variable. The log prints counts only; names go to the private healthchecks ping. It trusts the dates in the variable and does not ask GitHub or Databricks for the real expiry. |
| `check_workflow_state.py` | Tripwire: is every workflow of this repository still `active`? Weekly workflow `.github/workflows/workflow-state.yml` (Mondays 05:00 UTC; a manual run takes an `expect_state` input). Replaces guessing about GitHub's 60-day rule for scheduled workflows: it reads each workflow's state from the Actions API and fails when one is disabled. |
| `bootstrap/create_landing_volume.py` | One-time setup of the landing schema, volume and the pipeline user's grants. |
| `tests/` | Unit tests for orphan detection, taxonomy naming and change detection, delete-marker classification and the archive checks, on real file names and real records. |

Run the tests from the repository root: `python -m pytest p1_intake/tests`.

**Limits.** The archive was proven on one full pass (56 objects, 388.8 MB); only a small restore from it (3 files, no B2) has been drilled, not a full rebuild. B2's free
daily download cap was reached once during testing, so a re-run of the full archive that day would fail until it resets. **A lost archive manifest** used to mean a full re-download: the archive
job treated every B2 key that is not in the manifest as still to archive (confirmed from the code on 2026-10-18; the 2026-10-15 crash test did it for all 56 files; about 512 MB in 78 files, growing 28 MB a day,
which would have stopped fitting in B2's free 1 GB daily download cap in about 17 days: inferred from the landing sizes and the older cap figures, which the newer B2 documentation no longer states). The guard added the same
day refills the done list from the Hugging Face file listing (path, size and LFS sha256 checked against B2 and the capture's record, nothing downloaded) and archives only what does not match; the run goes red once to say so.
A real dry run with no manifest rebuilt 62 of 78 entries and left 16 small files (0.1 MB). A rebuilt entry did not get the B2 ETag or gzip check (nothing was downloaded); it says so in the manifest. GitHub's
scheduler runs the workflows hours late (see the top-level README); OFF publishes the daily delta between 06:19 and 06:33 UTC (13 days measured on 2026-10-18).

**Still to do in P1:** the token revocation checklist (the keep-alive is `.github/workflows/keepalive.yml`, best effort and unproven; see the top-level README); the decided capture change (the
capture becomes the first task of the Databricks job, with the GitHub capture kept as a second path).
Terraform for GitHub and Databricks objects is tracked under P3.
