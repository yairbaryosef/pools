# Atlas security review

**Status: BLOCKED**

This is the latest static security review of the current implementation. No
code was modified. The explicit product decision is **username/password
registration and login**, not Google/OIDC. Stale Google documentation is a
follow-up, not an authentication decision blocker.

## Remediation confirmed by static review

The earlier SEC-001 through SEC-003 blocker claims are removed because the
current source contains the corresponding controls. This is not runtime
verification or release approval.

- **Answer privacy / tenant isolation (formerly SEC-001, high):** group reads
  now return the allowlisted `_public_group()` shape, and pool reads/listings
  use `_public_pool()` without `answers` or audit rows
  (`src/atlas/application/services.py:110-154`). The repository group read also
  excludes audit events (`src/atlas/database/repositories.py:266-267`).
  Results are counts only and require a closed pool
  (`src/atlas/api.py:407-416`; `src/atlas/database/repositories.py:436-452`).
- **Replay/idempotency (formerly SEC-002, high):** every unsafe request now
  requires one valid `Idempotency-Key`; the claim is scoped by principal,
  group, method, and route, and mismatched payloads are rejected
  (`src/atlas/api.py:149-214`). Saved response headers, including cookies, are
  replayed (`src/atlas/api.py:216-234`; `src/atlas/database/repositories.py:247-264`).
  The persistence claim is atomic and expiry-aware
  (`src/atlas/database/repositories.py:217-245`).
- **Abuse and resource growth (formerly SEC-003, high):** authentication has
  per-IP and per-account shared abuse buckets (`src/atlas/api.py:53-121`), with
  Mongo-backed atomic enforcement (`src/atlas/database/repositories.py:70-144`).
  Request bodies, pagination, fields, and embedded members/pools/answers/audit
  records have bounded limits (`src/atlas/api.py:132-160,343-347`;
  `src/atlas/database/repositories.py:18-32,328-423`).

## Confirmed controls and residual risks

- **Authentication/session:** password hashes use fixed-parameter scrypt and
  bounded verification; unknown users receive one dummy verification
  (`src/atlas/application/services.py:38-65,81-94`). Sessions store a hash,
  are revocable/expiring, and the raw token is sent only in an HttpOnly,
  Secure, SameSite=Lax cookie (`src/atlas/api.py:288-310`;
  `src/atlas/database/repositories.py:199-215`). Runtime auth-abuse, cookie,
  and session-revocation evidence is still required.
- **Authorization/CSRF:** membership and admin checks protect group, pool,
  lifecycle, and answer actions (`src/atlas/application/services.py:110-174,
  196-208,223-240`). Unsafe cookie requests validate duplicate/conflicting
  Origin/Referer headers and the allowlist; SameSite is defense in depth
  (`src/atlas/api.py:81-99`). Proxy-origin behavior and browser negative tests
  remain unverified.
- **Input/output/XSS:** DTOs reject unknown fields and bound body/field sizes
  (`src/atlas/api.py:20-41,132-160`); the frontend static contract requires a
  restrictive CSP and no inline handlers/HTML sinks
  (`frontend/tests/security-contract.mjs:10-29`). Browser execution, build,
  deployed headers, Unicode normalization/confusable handling, and log review
  remain unverified.

## Evidence gaps and environment blockers

Required before release: execute and retain evidence for contract, browser,
concurrency/replay, Mongo integration, syntax/build, dependency, and deployed
security-header tests. Specifically include cross-member response privacy,
same-key/different-payload rejection, concurrent claims, cookie preservation,
multi-worker abuse limits, boundary size limits, CSRF duplicate/malformed
headers, and session revocation. A skipped or unavailable run is not evidence
of safety. The current review has no verified runtime, browser, Mongo,
dependency, or deployment execution evidence.

## Documentation follow-up

`docs/SECURITY.md:5-25`, `docs/AUTHENTICATION.md:3-23`, and `docs/API.md:9-23`
still describe Google/OIDC. Update them and related product, data-flow, and
frontend documentation to the accepted username/password model, including
password recovery and migration policy. **Owner:** product/documentation and
authentication owner. Do not treat this follow-up as evidence of OAuth support.

## Release status and handoff

Static remediation status is **READY for security re-review**, but release
status remains **BLOCKED** pending the runtime evidence and environment
verification above. Residual risks are therefore unresolved at the release
gate; remediation/evidence owner is backend, database, operations, frontend,
and release engineering as applicable. No explicit exception or product
decision is pending in this review.
