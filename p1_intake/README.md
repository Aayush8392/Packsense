# P1 — Intake

Gets Open Food Facts data into the platform every day and proves it arrived: the daily delta capture, the landing volume,
taxonomy snapshots and the tripwires that watch them. Runs entirely on GitHub Actions and Databricks; no laptop in the chain.

| File | What it does |
|---|---|
| `capture_deltas.py` | Downloads every OFF delta file not yet landed, checks it, uploads to B2 (upload-only key) and the landing volume, writes a manifest. Recovers orphaned landing files (landed, but in no manifest). Workflow: `.github/workflows/capture.yml` (07:30 UTC). |
| `capture_taxonomies.py` | Snapshots 34 OFF taxonomies, stored only when they change, plus a daily log of the version in force. Same workflow, second step. |
| `check_freshness.py` | Tripwire: is the newest OFF delta in landing? Workflow: `.github/workflows/freshness.yml` (11:00 UTC), alerts through healthchecks.io. |
| `check_delete_markers.py` | Tripwire: has anything hidden an object in the capture bucket (an upload-only B2 key can hide objects)? Lifecycle-aware; workflow `.github/workflows/delete-markers.yml` (11:30 UTC) with a `self_test` input that makes a real marker to prove the alert. |
| `archive_lib.py`, `notebooks/archive_to_hf.py`, `bootstrap/create_archive_job.py` | The archive job: every object in B2 (`raw/`, `taxonomies/`) is copied to a private Hugging Face dataset, each file checked (size, B2's checksum, gzip complete, the capture's recorded sha256) and compared with what Hugging Face reports storing; the archive manifest is written last. Daily Databricks job at 16:00 UTC. It never deletes from B2. A setup crash is reported to healthchecks as a failure. |
| `retention_lib.py`, `notebooks/landing_retention.py` | Landing retention, the second task of the archive job (runs only if the archive succeeded). A landed delta file is deleted only if it is older than 30 days (by the end time in its name; OFF keeps about 14 days listed, and the capture decides what to fetch from what is in landing), bronze loaded it, and the Hugging Face archive holds the same sha256. At most 20 deletions per run, a dry-run switch, never touches manifests or taxonomy snapshots. After 30 days a rebuild reads the HF archive, not landing. Failures ping the archive healthcheck as `/fail`. |
| `bootstrap/create_landing_volume.py` | One-time setup of the landing schema, volume and the pipeline user's grants. |
| `tests/` | Unit tests for orphan detection, taxonomy naming and change detection, delete-marker classification and the archive checks, on real file names and real records. |

Run the tests from the repository root: `python -m pytest p1_intake/tests`.

**Limits.** The archive was proven on one full pass (56 objects, 388.8 MB); a restore from it has not been drilled. B2's free
daily download cap was reached once during testing, so a re-run of the full archive that day would fail until it resets. GitHub's
scheduler runs the workflows hours late (see the top-level README).

**Still to do in P1:** B2 reconciliation, keep-alive for the free-tier accounts, token revocation checklist. Terraform for GitHub and
Databricks objects is tracked under P3.
