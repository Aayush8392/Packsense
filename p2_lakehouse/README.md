# P2 — Lakehouse

Turns landed files into queryable layers on Databricks: bronze (raw, append-only), then silver (typed, checked, scrubbed).

| File | What it does |
|---|---|
| `notebooks/bronze_load.py` | Loads landed delta files into `workspace.packsense_bronze.bronze_delta_raw`. Idempotent: insert-only MERGE on `(code, last_modified_t)`, a manifest row written last, and a row-count check against the capture manifest. |
| `notebooks/silver_load.py` | Bronze -> silver, per finished bronze file: silver rows, quarantine rows (broken records only), a hand-off check, then the manifest row. Idempotent and order-independent (every record is handled on its own); runs as the second task of the job (even if bronze ended red); pings healthchecks `packsense-core`. The decisions live in `silver_lib/`; the notebook only does the Spark reads and writes. |
| `silver_lib/run.py` | Processes one batch of bronze rows (each record on its own, so no file or row order can change a result), returning silver rows, quarantine rows and the run counters. Pure Python, tested on real records. |
| `bootstrap/create_bronze_job.py` | Creates the bronze schema and the scheduled Databricks job (`create`, `run`, `schedule`, `status`). The job has two tasks, bronze then silver (silver runs even if bronze ended red), both read from this repository's `main` branch. |
| `bootstrap/create_hmac_key.py` | Creates the HMAC key that scrambles contributor usernames in silver and stores it in secret scope `packsense` (`hmac_key_v1`). The key is generated in memory and never printed or written to disk; there is no escrow copy (if lost: new key, silver rebuilt from bronze, every contributor gets a new code). `create`, `check`, `dry-run`, and `put-secret` (stores another secret, such as a healthchecks ping URL, from a hidden prompt; refuses to touch the HMAC key). |
| `contracts/silver.yml` | The silver data contract, version 2: the allowlist of 71 columns (everything else is dropped), the scrub patterns, shape checks, own-handle redaction, the egress rules and quarantine codes. Read by the code; changing a column means changing this file. |
| `silver_lib/` | The silver logic as plain Python, unit-tested without Spark: `contract.py` (load/validate v2), `personal.py` (HMAC, scrub, own-handle redaction, fingerprint, quantity parsing, shape checks), `transform.py` (raw record -> silver row or coded quarantine row), `schema.py` (table definitions generated from the contract), `egress.py` (the one exit function every export path calls). |
| `tests/` | `python -m pytest p2_lakehouse/tests` from the repo root. Fixtures are real bronze records, sanitised (see `tests/fixtures/README.md`). |
| `bootstrap/extract_fixtures.py` | Regenerates the fixtures inside Databricks (names never leave it). |

**Still to do in P2:** silver (contracts, quarantine, HMAC, field-aware scrub, lineage), India seed, one-time dump read for
`input_sets`, schema-drift monitor, Asset Bundle deployment (tracked under P3).
