# Terraform: B2 bucket and repository secrets

Creates the private, versioned raw-capture bucket in Backblaze B2 (lifecycle: `raw/` hidden after 270 days, `tmp/` after 7, hidden files kept 30 days), an upload-only key scoped to that bucket, and writes that key into this repository's Actions secrets (`B2_UPLOAD_KEY_ID`, `B2_UPLOAD_APPLICATION_KEY`) and variables (`B2_BUCKET`, `B2_S3_ENDPOINT`).

State is stored in a private B2 bucket through the S3-compatible backend (no locking; a single-run concurrency group serialises runs). The bucket name is a plain value, not a secret.

## Repository secrets this workflow reads
| Secret | Purpose |
|---|---|
| `TF_STATE_KEY_ID`, `TF_STATE_APP_KEY` | B2 key scoped to the state bucket only |
| `B2_TF_KEY_ID`, `B2_TF_APP_KEY` | B2 key allowed to create buckets and keys (setup only; remove and revoke after the first apply) |
| `GH_TF_TOKEN` | Fine-grained GitHub token limited to this repository: Secrets read/write, Variables read/write, Administration read/write (rulesets and the deploy key) |

## Rules on `main` (two rulesets, on purpose)
- **`protect-main`:** no deletion, no force-push, linear history, no bypass for anyone.
- **`require-ci`:** the checks `tests` and `lint` (from the GitHub Actions app) must have passed on a commit before `main` can move to it. Its only bypass is one **deploy key** (`keepalive`, public half in `keepalive_deploy_key.pub`, private half in the repository secret `KEEPALIVE_DEPLOY_KEY`, never in Terraform or its state), used by the keep-alive workflow: its empty commit can never carry a CI result, GitHub Actions cannot be added to a ruleset's bypass list, and a push with the built-in token starts no other workflow. The two rules are separate rulesets because a bypass skips the whole ruleset it is attached to: the key can skip the CI check but cannot delete `main` or force-push it (tested in a throwaway repo before this was applied).
- Working with it: push a branch (CI runs on every branch push), wait for `tests` and `lint` to pass on that commit, then move `main` to the same commit. If CI itself is broken, the owner can edit or disable `require-ci` in the repository's rule settings, fix CI, and turn it back on. If the deploy key leaks: delete the deploy key and the secret, make a new pair, commit the new public key and apply.
- The two resources are applied with the workflow's `target` input, one per run (`github_repository_deploy_key.keepalive`, then `github_repository_ruleset.require_ci`), because the b2 provider cannot start without the admin B2 key.

## Running it
Actions tab, "Terraform (B2 bucket and repository secrets)", Run workflow: `plan` first, then `apply`. Pull requests that touch `infra/terraform/` run `plan` only, and never for forks.
