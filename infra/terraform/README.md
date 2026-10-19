# Terraform: two roots

Since the split (P5 step 1) there are two independent roots. They share one state bucket (`tfstate-aayush`, private, versioned, reached through B2's S3-compatible API, no locking; one concurrency group serialises runs) under different state keys.

| Root | State key | What it holds | Credentials | Workflow |
|---|---|---|---|---|
| `b2/` | `packsense/terraform.tfstate` | the private, versioned raw-capture bucket (lifecycle: `raw/` hidden after 270 days, `tmp/` after 7, hidden files kept 30 days), the upload-only key and the read-only key, and the repository secrets and variables derived from them (`B2_UPLOAD_*`, `B2_READ_*`, `B2_BUCKET`, `B2_S3_ENDPOINT`) | the state key, **the temporary B2 admin key**, `GH_TF_TOKEN` | `terraform-b2.yml` (manual only) |
| `github/` | `packsense/github.tfstate` | the rulesets `protect-main` and `require-ci` and the `keepalive` deploy key | the state key and `GH_TF_TOKEN` only | `terraform-github.yml` (pull requests, plan on manual runs, apply on manual runs behind approval) |

The split exists so that a GitHub-only change (a ruleset) no longer needs the B2 admin key: pull-request plans of `github/` work, and the admin key is needed only for `b2/`.

## Repository secrets the workflows read
| Secret | Used by | Purpose |
|---|---|---|
| `TF_STATE_KEY_ID`, `TF_STATE_APP_KEY` | both | B2 key scoped to the state bucket only |
| `B2_TF_KEY_ID`, `B2_TF_APP_KEY` | `b2/` only | B2 key allowed to manage buckets and keys (all buckets, all capabilities). Setup only: add before a `b2/` run, delete the secrets and the key after |
| `GH_TF_TOKEN` | both | Fine-grained GitHub token limited to this repository: Secrets read/write, Variables read/write, Administration read/write (rulesets and the deploy key). It expires; the expiry alarm is in `SECRET_EXPIRY_LIST` |

## How the split was made (no `terraform state mv`)
`b2/` kept the original state key, so nothing moved. `github/` has a new state key and adopts the live objects with `import` blocks (the two ruleset ids are fixed; the deploy key's id is read from the API by the workflow and passed as `TF_VAR_keepalive_deploy_key_id`). `b2/` carries three `removed` blocks with `destroy = false`, which make the old state forget the same three resources without touching them on GitHub. Apply `github/` first, then `b2/`, then delete the `removed` blocks from `b2/` in a later commit.

## Rules on `main` (two rulesets, on purpose)
- **`protect-main`:** no deletion, no force-push, linear history, no bypass for anyone.
- **`require-ci`:** the checks `tests` and `lint` (from the GitHub Actions app) must have passed on a commit before `main` can move to it. Its only bypass is one **deploy key** (`keepalive`, public half in `github/keepalive_deploy_key.pub`, private half in the repository secret `KEEPALIVE_DEPLOY_KEY`, never in Terraform or its state), used by the keep-alive workflow: its empty commit can never carry a CI result, GitHub Actions cannot be added to a ruleset's bypass list, and a push with the built-in token starts no other workflow. The two rules are separate rulesets because a bypass skips the whole ruleset it is attached to: the key can skip the CI check but cannot delete `main` or force-push it (tested in a throwaway repo before this was applied).
- Working with it: push a branch (CI runs on every branch push), wait for `tests` and `lint` to pass on that commit, then move `main` to the same commit. If CI itself is broken, the owner can edit or disable `require-ci` in the repository's rule settings, fix CI, and turn it back on. If the deploy key leaks: delete the deploy key and the secret, make a new pair, commit the new public key and apply `github/`.

## Running it
Actions tab: "Terraform (GitHub rulesets and deploy key)" or "Terraform (B2 bucket and repository secrets)", Run workflow: `plan` first, then `apply`. Pull requests that touch `infra/terraform/github/` run its `plan` only, and never for forks.
