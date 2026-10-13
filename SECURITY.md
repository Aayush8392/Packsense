# Security policy

PackSense is a personal portfolio project. It applies enterprise-style *controls* but has no external penetration test, certification or round-the-clock monitoring.

## Reporting a problem
Open a private security advisory on the GitHub repository, or email the repository owner. Please do not post secrets or exploit details in a public issue.

## Controls in place or planned (see `docs/design-v4.2.md`, section 10)
- No keys in code; secret scanning and push protection; secrets only through secret scopes or CI secrets, never job parameters.
- Scoped, expiring tokens; a dated rotation checklist and a timed rotation drill.
- One writer per data layer, enforced by grants and tests; contributor usernames pseudonymised with an HMAC whose key is held in a secret scope and an offline escrow copy.
- A field-aware scan keeps emails and phone patterns out of published outputs; a licence gate keeps attribution on every release.
- Pull-request workflows never receive secrets; Actions are pinned to commit SHAs with minimal permissions.
- AI components are read-only or propose-only and treat product text as data.
