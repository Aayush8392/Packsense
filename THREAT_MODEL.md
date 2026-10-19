# Threat model

One page on what could go wrong and what stands in the way, for the three threats that matter most to this project: **a leaked secret**, **a compromised
dependency or build step** and **prompt injection through product text**. PackSense is a one-person project: every identity belongs to the same owner, so the
owner's account security (unique passwords, two-factor authentication, offline recovery codes) is itself a control, and nothing here claims enterprise
assurance (no external penetration test, no certification, no round-the-clock monitoring). Status words are strict: **built** means it exists and was
exercised; **designed** means it is written down and not built yet. Dates, secret names and values are deliberately not in this public file.

## What is worth protecting
| Asset | Why it matters |
|---|---|
| Databricks admin access | can read everything, including the raw OFF records that still hold plaintext contributor usernames, and change any grant |
| The HMAC key for contributor codes | with it, anyone could re-derive codes from OFF's public usernames (the codes already protect only against our own readers) |
| The archive (raw history and one full dump) | irreplaceable: a point-in-time copy of the catalogue that cannot be recreated for free |
| The GitHub repository and its deploy path | a change that reaches `main` and is approved reaches production |
| The public outputs (site, scores, releases) | wrong or personal data published under our name; licence breach |

## Threat 1: a secret leaks
| How it could happen | Controls (built unless marked) | Residual risk |
|---|---|---|
| A secret committed to the repository or pasted into a log or chat | secret scanning with push protection; gitleaks over the full history on every push and weekly (pinned version, one scoped allow-rule); secrets reach jobs only through secret scopes, never as job parameters (an early test run exposed a token as a parameter: fixed and re-issued); `.env` is local and ignored; context files hold no secrets and stay local; scripts never print a value | a human can still paste a secret into a chat or screenshot; a ping URL is a capability token and was once visible in a screenshot (regenerate on any exposure) |
| A long-lived credential stolen from the laptop | the Databricks admin token carries an expiry; no admin credential exists in CI; nobody holds a service principal's secret (a script rotates all four, 90-day lifetime with overlap, and writes them straight into the places that use them); a daily tripwire warns 10 days before any listed secret expires | two credentials have no expiry by choice (a repo-deploy key and a narrow rotation token), limited by scope and watched by alerts; laptop compromise remains the largest single risk |
| A job or workflow exposes a secret to code it should not trust | each environment holds only its own principal's secret; production deploys need the owner's approval and cannot be bypassed by an administrator; workflows from forks and Dependabot receive no secrets; one workflow that does hold a repository-admin token runs for same-repo branches only, and only the owner can push one | a malicious branch pushed by a compromised owner account would reach that token |
| A principal is over-privileged | grants live in one file, applied by script, compared with the live workspace every night (any extra or missing grant turns the check red); the nightly policy job signs in as every identity and proves what it may and may not do; each deny check is tested to fail when its action is allowed | the policy job tests what is listed, not everything an identity could try |
| Contributor names exposed | codes never leave silver (`egress: never`), are masked in Unity Catalog and are absent from gold (all tested); raw records are read by no analyst or export | OFF publishes the names itself: the protection is against our own readers only (see `PRIVACY_AUDIT.md`) |

**If one leaks:** revoke it at the source, rotate with the rotation script where one exists, check the audit log and the run history for use, and note the cause. A lost HMAC key means re-keying and rebuilding silver from bronze (runbook, drilled on scratch).

## Threat 2: a dependency or build step is compromised
| How it could happen | Controls (built unless marked) | Residual risk |
|---|---|---|
| A malicious or hijacked GitHub Action | every action pinned to a commit SHA with its version in a comment; minimal `permissions`; no credential persistence on checkout (the keep-alive pushes by design and is a documented, accepted exception); a workflow linter (zizmor) runs on every change | a pinned action can still be malicious from the start; the pin removes silent updates, not review |
| A hijacked Python package | direct versions pinned and chosen at least two weeks after release; weekly Dependabot and a dependency audit on every change; no third-party dbt packages (so no extra downloads or macros run under the gold identity); one package held back on purpose | **no hash locking** of Python dependencies (designed, not done): a compromised release of a pinned version would install; transitive packages are not pinned by hash |
| A tampered infrastructure provider or CLI | the Databricks CLI version is pinned; Terraform providers are constrained by version range and state lives in a private versioned bucket | **no committed provider lock file** (a gap: the next init could take a newer allowed release) |
| An unreviewed change reaches production | `main` requires CI on the exact commit; production jobs run a fixed deployed copy owned by a principal, so a push alone changes nothing; deploys to production wait for the owner's approval; the deploy key that can bypass CI cannot delete or force-push `main` | one reviewer who is also the author: review catches mistakes, not a compromised owner |
| Poisoned input data (OFF is crowd-edited) | untrusted by design: schema validation, size and decompression limits, nothing executed from data, quarantine with coded reasons, a schema-drift monitor that alerts on shape changes | a plausible-looking wrong value passes; the project labels data "consistent" or "flagged", never "correct" |
| The platform fails or changes terms | tripwires on freshness and delete markers, a dead-man ping on the scheduled jobs, an archive independent of Databricks, a keep-alive for scheduled workflows | free-tier quotas and terms can change (register in the design) |

## Threat 3: prompt injection through product text
Any product name, brand or comment is written by an anonymous editor, so it is **untrusted text**. **No language model runs in production today**: the steward agent,
the AI explanation layer and the AI-drafted dashboard pages are **designed, not built**. These are the rules they must keep, and they are tested when built:

| Risk | Design commitment (designed) |
|---|---|
| Text tells the model to act or leak | models never act: the steward agent has read-only tools and its output is a schema-validated proposal that a human decides; the explanation layer is describe-only, it never suggests actions |
| Text smuggles instructions or markup into a page | product text is wrapped as data; imperative constructions in tool output are neutralised; output is never rendered as markdown or links; a canary string in tool outputs shows when text leaks into output |
| The model invents a number or an explanation | code computes every fact, the model narrates, and a checker confirms every number and named column against the cited facts; it verifies numbers, not meaning, and the stories say so; no hypotheses are generated |
| Personal data reaches a prompt | user fields are projected out inside the tools; a test asserts no raw username in any logged prompt; every outgoing text passes the one exit function; provider zero-data-retention is on |
| Cost or availability abuse | no public chat endpoint: serving is static files and a precomputed question catalogue matched in the browser; a daily token budget with a pre-flight assertion |

**Today's exposure** is therefore the data path only (poisoned input above) and the development tooling: coding assistants read local files and run commands under a
permission layer that has refused credential reads and production-changing actions when asked, and the owner runs the production steps.

## What this model does not cover
Physical access to the owner's devices, a compromise of GitHub, Databricks, Backblaze or Hugging Face themselves, legal and regulatory questions (the project aligns with
data-protection principles such as minimisation and pseudonymisation and claims neither anonymisation nor compliance), and denial of service against free-tier services.

Related: [`SECURITY.md`](SECURITY.md) (reporting and controls), [`DATA_CLASSIFICATION.md`](DATA_CLASSIFICATION.md), [`PRIVACY_AUDIT.md`](PRIVACY_AUDIT.md), `docs/design-v4.2.md` section 10.
