# Security policy

PackSense is a personal portfolio project. It applies enterprise-style *controls* but has no external penetration test, certification or round-the-clock monitoring.
Read [`THREAT_MODEL.md`](THREAT_MODEL.md) for what could go wrong and what stands in the way; this file is the reporting policy and the list of controls.

## Reporting a problem
Open a private security advisory on the GitHub repository, or email the repository owner. Please do not post secrets or exploit details in a public issue.
This is a one-person project: expect a reply when the owner next looks, not within a fixed time.

## Controls that exist (built and exercised)
- **Secrets:** no keys in code; secret scanning with push protection; gitleaks over the full history on every push and weekly; secrets reach jobs only through secret scopes or CI environment secrets, never job parameters; no Databricks admin credential in CI; service principal secrets are rotated by one script (90-day lifetime with overlap) and nobody holds them; a daily tripwire warns before a listed secret expires.
- **Access:** every grant is in one checked-in file, applied by script and compared with the live workspace every night; a nightly job signs in as each identity (service principals as run-as jobs, so no stored secret) and proves what it may and may not do; one writer per data layer; the analyst role sees only India rows of the market tables (row filter) and masked contributor codes (`p5_governance/policies.yml`).
- **Personal data:** contributor usernames are pseudonymised with an HMAC (key in a secret scope, no escrow copy: a lost key means a re-key and a rebuild from bronze); the codes never leave silver, are masked in Unity Catalog and are absent from gold. OFF publishes the usernames itself, so this protects against our own readers only. Every column is classified in [`DATA_CLASSIFICATION.md`](DATA_CLASSIFICATION.md); what a scrub leaves is measured and dated in [`PRIVACY_AUDIT.md`](PRIVACY_AUDIT.md) (a bound, not a guarantee).
- **Releases:** a licence gate (`p5_governance/licence_gate.py`) checks the rendered output of an export for the Open Food Facts attribution and ODbL notice, no product images, score files limited to barcode, score and provenance, and no personal or internal column. It is not wired into an export yet; the first export (P6) must call it.
- **Build and delivery:** Actions pinned to commit SHAs with minimal permissions; `main` requires CI on the exact commit; production jobs run a fixed deployed copy and production deploys need the owner's approval; workflows from forks and Dependabot receive no secrets; workflow linting, dependency audit and CodeQL run on every change.
- **Untrusted input:** schema validation, size limits, nothing executed from data, quarantine with coded reasons, a schema-drift monitor.

## Controls that are designed but not built
- Hash-locking of Python dependencies and a committed Terraform provider lock file (a known gap: see the threat model).
- Everything that involves a language model (the steward agent, the AI explanation layer, AI-drafted dashboard pages). No model runs in production today; the rules they must keep are in the threat model and are tested when they are built.

## Limits
All identities belong to one person, so the owner's account security (unique passwords, two-factor authentication, offline recovery codes) is project security. Nothing here claims anonymisation or compliance with any law.
