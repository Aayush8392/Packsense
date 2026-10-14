# P1 — Intake

Gets Open Food Facts data into the platform every day and proves it arrived: the daily delta capture, the landing volume,
taxonomy snapshots and the tripwires that watch them. Runs entirely on GitHub Actions and Databricks; no laptop in the chain.

| File | What it does |
|---|---|
| `capture_deltas.py` | Downloads every OFF delta file not yet landed, checks it, uploads to B2 (upload-only key) and the landing volume, writes a manifest. Recovers orphaned landing files (landed, but in no manifest). Workflow: `.github/workflows/capture.yml` (07:30 UTC). |
| `capture_taxonomies.py` | Snapshots 34 OFF taxonomies, stored only when they change, plus a daily log of the version in force. Same workflow, second step. |
| `check_freshness.py` | Tripwire: is the newest OFF delta in landing? Workflow: `.github/workflows/freshness.yml` (11:00 UTC), alerts through healthchecks.io. |
| `bootstrap/create_landing_volume.py` | One-time setup of the landing schema, volume and the pipeline user's grants. |
| `tests/` | Unit tests for orphan detection and taxonomy naming and change detection, on real file names. |

Run the tests from the repository root: `python -m pytest p1_intake/tests`.

**Still to do in P1:** delete-marker tripwire (needs a read-only B2 key), archive job (B2 → Hugging Face), keep-alive, token
revocation checklist. Terraform for GitHub and Databricks objects is tracked under P3.
