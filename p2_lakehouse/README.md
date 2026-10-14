# P2 — Lakehouse

Turns landed files into queryable layers on Databricks: bronze (raw, append-only), then silver (typed, checked, scrubbed).

| File | What it does |
|---|---|
| `notebooks/bronze_load.py` | Loads landed delta files into `workspace.packsense_bronze.bronze_delta_raw`. Idempotent: insert-only MERGE on `(code, last_modified_t)`, a manifest row written last, and a row-count check against the capture manifest. |
| `bootstrap/create_bronze_job.py` | Creates the bronze schema and the scheduled Databricks job (`create`, `run`, `schedule`, `status`). The job runs the notebook from this repository's `main` branch. |
| `bootstrap/create_hmac_key.py` | Creates the HMAC key that scrambles contributor usernames in silver and stores it in secret scope `packsense` (`hmac_key_v1`). The key is generated in memory and never printed or written to disk; there is no escrow copy (if lost: new key, silver rebuilt from bronze, every contributor gets a new code). `create`, `check`, `dry-run`. |

**Still to do in P2:** silver (contracts, quarantine, HMAC, field-aware scrub, lineage), India seed, one-time dump read for
`input_sets`, schema-drift monitor, Asset Bundle deployment (tracked under P3).
