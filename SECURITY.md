# Security policy

PackSense is a personal portfolio project. It applies enterprise-style *controls* but has no external penetration test, certification or round-the-clock monitoring.

## Reporting a problem
Open a private security advisory on the GitHub repository, or email the repository owner. Please do not post secrets or exploit details in a public issue.

## Controls in place or planned (see `docs/design-v4.2.md`, section 10)
- No keys in code; secret scanning and push protection; secrets only through secret scopes or CI secrets, never job parameters.
- Scoped, expiring tokens; a dated rotation checklist and a timed rotation drill.
- One writer per data layer, enforced by grants and tests; contributor usernames pseudonymised with an HMAC whose key is held in a secret scope and an offline escrow copy.
- Every column is classified public, personal or internal in [`DATA_CLASSIFICATION.md`](DATA_CLASSIFICATION.md), generated from the silver contract and kept in step by tests; personal columns are `egress: never`, masked in Unity Catalog, and absent from gold. Gold tables are row-filtered per market for the analyst role (`p5_governance/policies.yml`).
- A field-aware scan keeps emails and phone patterns out of published outputs; a licence gate keeps attribution on every release.
- Pull-request workflows never receive secrets; Actions are pinned to commit SHAs with minimal permissions.
- AI components are read-only or propose-only and treat product text as data.
