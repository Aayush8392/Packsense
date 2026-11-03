# The flag-triage model: custom registry, weekly scoring and the pre-registered measurement

Roadmap Phase D item 20 (design 7.7). This page says how model versions are kept, what scores them each week, and **fixes the measurement of the refit before any of its data exists**
(the commit that adds this page is the time stamp). It holds no measured figures: those stay with the owner.

## Why a custom registry

The managed Unity Catalog registry cannot be used on Databricks Free Edition. Registering a model creates the entry, then the upload of the model files to the catalog's managed storage is
refused (S3 `AccessDenied` on `PutObject`; reproduced on 2026-11-03, the half-made entry was deleted). MLflow tracking works. So a version is one file in the Unity Catalog volume
`workspace.packsense_snapshots.models` plus one row in the Delta table `workspace.packsense_snapshots.model_versions` (version, stage, recipe hash, parent, the snapshot dates it was trained on,
row counts, configuration, code hashes, scikit-learn version, file path and sha256, measured figures, note, approver, time). A file is loaded only if its hash is the registered one.
Enterprise mapping: this is the same record a managed registry keeps (versions, stages, lineage, approvals) in two objects we own.

Stages: `measured_reference`, `production`, `archived`. The weekly run scores with the newest `production` and the newest `measured_reference`.

## The versions

| Version | Stage | What it is |
|---|---|---|
| 1 | `measured_reference` | The model measured under freeze `e22b9b02196d`: its code files, configuration and seed, trained on its own training weeks (the first four snapshots from 2026-07-26). Retrained for the registry, not byte-compared with the original fit. |
| 2 | `production` | The same recipe (same four code files, configuration and seed) trained on every labelled week from 2026-03-22 to 2026-10-04 (29 snapshots). **Not measured**: every week it knows is training data. |

`triage_export.py` is deliberately not one of the four frozen code files, so exporting never changes the identity of a measured model.

## Weekly scoring

The task `score` of the job `packsense-snapshots` runs after `open_flags`: every open error flag of the newest finished snapshot is scored by each live version, with features built the way that
version's own training weeks were. Rows go to `triage_scores` (one row per flag and version) and distribution figures to `triage_score_stats` (flags, products, score quantiles, missing share of
each feature) for the drift check. Both tables are internal; nothing is published from them here.

## The measurement of the recipe, fixed on 2026-11-03 (before any of its test weeks is scored or labelled)

The question: does the recipe, trained on a long history, still beat the simple baselines on weeks it has never seen? The live model (version 2) is that recipe trained on 29 weeks, so the
claim is about the recipe, and it is stated that way.

- **Week numbers** count the snapshots from 2026-03-22 as week 0 (2026-09-06 is week 24, 2026-10-04 is week 28, 2026-10-18 is week 30).
- **Label:** the same as before, window 4 (a flag open at snapshot t is positive if it is gone, the product edited and the family not just renamed within 4 snapshots), the two OFF-side jump weeks excluded.
- **Training weeks 0 to 24** (2026-03-22 to 2026-09-06). **Purged weeks 25 to 27** (2026-09-13 to 2026-09-27): a training week is used only if its label window ends at or before the first test week.
  The purged block holds the test weeks of the first freeze, so no earlier test week is reused anywhere.
- **Test weeks 28 to 30** (2026-10-04, 2026-10-11, 2026-10-18). No freeze has scored them. They are all labelled once the snapshot of 2026-11-15 is read (about 2026-11-16).
- **Population and kill rule: unchanged.** Precision at the top 1,000 among uncovered error flags; PASS only if the model beats the best baseline and the lower end of its 95% Wilson interval is above
  that baseline's point estimate. Models: with and without the family feature, as in the first run.
- **Measured once** for the freeze hash. The run is `freeze` then `final` of `notebooks/triage_run.py` with `last_week=30` (so the split does not move when week 31 gets its labels):

  `python p7_triage_ml/bootstrap/run_triage.py --env-file .env --branch main --param mode=freeze --param steps=4 --param last_week=30`, then the same with `mode=final --param freeze_hash=<hash printed>`.
- **What is reported:** the kill rule result and the figures of that run, as the owner's. If the recipe fails the rule, only the baseline ranking and the coverage table are published and production returns to
  the baseline ranking.

## Forward monitoring (not a gate)

From the snapshot of 2026-11-01 on, both live versions score each week. Once at least four scored snapshots dated 2026-11-01 or later have complete outcomes (about 2026-12-20), the same precision at
the top 1,000 is computed for both versions on the same weeks and reported as monitoring. Snapshots before 2026-11-01 are never used for version 2: its training labels already looked ahead into
October. Retrospective scores of October snapshots, if written, are monitoring of the score distribution only.
