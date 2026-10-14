# PackSense

A daily-updated, cleaned and versioned copy of the [Open Food Facts](https://world.openfoodfacts.org) product catalogue, India first, built the way a company data team would build it.

> **Status: design frozen (v4.2), build starting.** This README is a stub. The architecture is in [`docs/design-v4.2.md`](docs/design-v4.2.md).

## What it does
- Picks up what changed on Open Food Facts every day, without any laptop being on, and keeps the full history.
- Cleans and stores the data in layers (raw, tidy, business-ready) on a lakehouse.
- Scrambles contributor usernames and checks that no emails or phone numbers slip through.
- Finds arithmetic and physical errors in nutrition data and ranks which suspicious products to fix first.
- Tracks products that disappear (roughly 1.8% of recently changed products are deleted or merged within days).
- Lets an AI assistant **propose** fixes into a review queue; a human always decides.
- Publishes a public dashboard with pipeline health, a monthly India data release, and a static score lookup.

## Principles
- ₹0 recurring cost, free tiers only, every limit tracked.
- Real data only, no synthetic data.
- No bulk data on a local machine; a workstation is a control point, not a warehouse.
- Every tool has a real job; nothing is here only to show a keyword.
- Everything claimed was tested on real accounts and real data first (41 verification items before the first commit of the build).

## Data and licence
Code is Apache-2.0 (see [`LICENSE`](LICENSE)). Data comes from Open Food Facts under the [ODbL](https://opendatacommons.org/licenses/odbl/1-0/); published data releases carry the required attribution and share-alike terms. Product images are not redistributed.

## Layout (grows as the build progresses)
```
p1_intake/       P1: daily capture, landing, taxonomy snapshots, tripwires
p2_lakehouse/    P2: bronze and silver on Databricks
infra/terraform/ shared infrastructure as code (B2 bucket, repository secrets)
docs/            design and evidence
.github/         workflows (they must live here), Dependabot, CODEOWNERS
```
Later modules get their own `pN_name/` folder when they start.
