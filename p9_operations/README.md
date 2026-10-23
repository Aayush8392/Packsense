# P9 Operations

Operating the pipeline: reconciliation, drills, capacity data. Today this folder holds one piece, the weekly OFF snapshot comparison
(roadmap Phase A). The deletion reconciliation on Airflow, the drills and the capacity panel come later.

## Snapshot flag history (`snapshot_lib.py`, `notebooks/snapshot_events.py`, job `packsense-snapshots`)

**Why.** The weak label for flag triage needs "the flag was on this product and then went away". Our own daily deltas only start on 30 Sep and
rarely show a product before its fix (99.7% of flag spans are already open when we first see the product), so waiting 30 days would still leave
the left-censoring. OFF's Hugging Face dataset `openfoodfacts/product-database` is rebuilt about twice a day and every build is a git commit:
667 commits back to 10 Oct 2025 were listed on 2026-10-20, and an old revision's `food.parquet` is still downloadable.

**What it does.** Once a week it picks one snapshot per week (the newest commit at or before each Monday 00:00 UTC). For every consecutive pair
that is not in `snapshot_manifest` it reads five columns of each (`code`, `last_modified_t` and the three data-quality tag lists) with DuckDB, compares
them and writes only the changes to `workspace.packsense_snapshots`:

| Table | One row is |
|---|---|
| `snapshot_flag_events` | a flag tag that disappeared from or appeared on a product present in both snapshots, with its family, whether the product was edited and whether the family remains |
| `snapshot_presence_events` | a barcode in the older snapshot and not in the newer (a deletion candidate) |
| `snapshot_open_counts` | how many products carried a flag tag at one snapshot |
| `snapshot_manifest` | one compared pair: counts, bytes read, run id (written last, so a crash is repaired by the next run) |

The snapshots themselves are never stored. No contributor field is read. All four tables are public or internal in `DATA_CLASSIFICATION.md`.

**The flag family.** OFF writes one check under several tags, a plain one and one per nutrition source and basis. A product that moves from the
plain tag to a source tag has not been fixed. `family_key` strips the source and basis, so the label is built on the family and `family_remains`
tells a rename from a fix. Measured 2026-10-20 on two snapshots 18 days apart: 176 of 215 error flags that looked unfixed were this move.

**Bounds (Databricks Free Edition publishes no storage or compute cap).**
- A byte guard stops any single snapshot read above 1 GB (a snapshot is about 310 MB for these columns).
- At most `max_pairs` pairs per run; the first run after a deploy is the 12-week backfill (about 3.7 GB, roughly 40 minutes).
- Events older than `retention_months` (13) are deleted at the end of a successful run, so the tables stay at tens of MB.
- The job is never retried automatically (`disable_auto_optimization`), because a retry would silently download another ~600 MB.
- The Hugging Face resolver allows 3,000 requests per 5 minutes; the signed CDN address is resolved once and read directly.

**One process per pair, and what the 2026-10-20 failure taught.** The first production run died (out of memory) after 7 of 12 pairs, with the seconds per pair
rising from 554 to 1,355. The notebook now runs every pair in its own Python process (`snapshot_lib.py worker`), keeps a snapshot read from the network as a
local Parquet file for the next pair, logs memory and seconds per pair, and stops itself (progress saved) when memory passes 60% of the machine or a pair takes more
than twice the median. `bootstrap/snapshot_soak.py` loops the comparison from local files and compares the old loop with the new one. **Result (12 and 8 iterations):**
the new loop is flat (39 to 50 s per iteration, notebook process 260 MB, worker peak 7.1 GB of 15.6 GB); the old loop was ALSO flat on local files (about 90 s, a
plateau at 6.6 GB), so the compute loop alone does not explain the failure. The cause is probably in reading from the network (not reproduced: the soak
reads local files); the process-per-pair design bounds it, but that is a protection, not a proof.

**Measured and not measured.** Reading cost per snapshot and the pair comparison are measured (three snapshots, 2026-10-20). What the label is
worth is measured only for error flags that OFF's own arithmetic rules can recompute (about 93% genuine numeric fixes at family level); warnings
and info flags were not examined, and a numeric fix is not proof of a correct value.

## Pipeline health (`health_lib.py`, `notebooks/health_collect.py`, bundle `health/`, job `packsense-health`)

Phase B item 9 (the capacity panel and dependency health). Once a day (08:40 UTC, after the gold build and before the publish) the job writes one long table,
`workspace.packsense_health.health_metric_daily` (day, subject, metric, value, unit, detail): per production job the runs, the runs that did not succeed, the longest
run and the hours since the last success (from `system.lakeflow.jobs` and `job_run_timeline`; a run is one `run_id`, the duration is end minus start because the table's
own duration column is empty), and per outside service whether one light request was answered (the same list as the monthly egress check) and how fast. Rows are merged by
(day, subject, metric), so a rerun and the three-day lookback never duplicate. Three "right now" timestamps are stored as Unix seconds under the subject `pipeline` (the Home page's status strip): `off_newest_file_published` (OFF's `Last-Modified` of its newest delta,
read from the newest capture manifests in the landing volume), `our_capture_landed` (when our capture received that file) and `gold_last_success`; a value that cannot be read gets no row, and
a manifest read failure only prints a warning. An unreachable service turns the task red after the rows are written. The public export
(`p6_serving/export_spec.yml`, dataset `pipeline_health`) and the site's health page read this table.

**The job is owned by the admin and has no service principal.** Measured 2026-10-21: Free Edition lets nobody grant the system tables to another identity (`GRANT` on the
`system` catalog needs MANAGE, which not even the admin holds), so a narrow principal cannot read them (one was created, refused, and removed). Like `packsense-policy`, the
bundle is deployed from the laptop by the admin (`cd p9_operations/health`, `bundle deploy`, `bundle run health_collect`; `--notebook-params dry_run=true` runs everything and
writes nothing). The schema and table are made by the admin (`bootstrap/setup_health.py create-schema`); the secret scope `packsense_health` holds only the ping URL.

**Not collected, on purpose:** storage size (`system.storage.table_metrics_history` is empty on Free Edition: 0 rows, measured 2026-10-21; `DESCRIBE DETAIL` needs SELECT on
the table) and any billing, quota or spend figure (kept off the public site by decision). The history starts on 2026-10-19, the first day the first run could look back to.

## Tests
`python -m pytest p9_operations/tests` from the repo root. The commit list, the tag list and the product slice in `tests/fixtures/` are real
(OFF's public history and two real snapshots), exported through the repo's exit function.
