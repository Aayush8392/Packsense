# Terraform: B2 bucket and repository secrets

Creates the private, versioned raw-capture bucket in Backblaze B2 (lifecycle: `raw/` hidden after 270 days, `tmp/` after 7, hidden files kept 30 days), an upload-only key scoped to that bucket, and writes that key into this repository's Actions secrets (`B2_UPLOAD_KEY_ID`, `B2_UPLOAD_APPLICATION_KEY`) and variables (`B2_BUCKET`, `B2_S3_ENDPOINT`).

State is stored in a private B2 bucket through the S3-compatible backend (no locking; a single-run concurrency group serialises runs). The bucket name is a plain value, not a secret.

## Repository secrets this workflow reads
| Secret | Purpose |
|---|---|
| `TF_STATE_KEY_ID`, `TF_STATE_APP_KEY` | B2 key scoped to the state bucket only |
| `B2_TF_KEY_ID`, `B2_TF_APP_KEY` | B2 key allowed to create buckets and keys (setup only; remove and revoke after the first apply) |
| `GH_TF_TOKEN` | Fine-grained GitHub token limited to this repository: Secrets read/write, Variables read/write |

## Running it
Actions tab, "Terraform (B2 bucket and repository secrets)", Run workflow: `plan` first, then `apply`. Pull requests that touch `infra/terraform/` run `plan` only, and never for forks.
