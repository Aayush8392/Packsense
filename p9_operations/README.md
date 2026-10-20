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

**Measured and not measured.** Reading cost per snapshot and the pair comparison are measured (three snapshots, 2026-10-20). What the label is
worth is measured only for error flags that OFF's own arithmetic rules can recompute (about 93% genuine numeric fixes at family level); warnings
and info flags were not examined, and a numeric fix is not proof of a correct value.

## Tests
`python -m pytest p9_operations/tests` from the repo root. The commit list, the tag list and the product slice in `tests/fixtures/` are real
(OFF's public history and two real snapshots), exported through the repo's exit function.
