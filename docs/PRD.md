# Product Requirements: Atlas Pools Server

## 1. Product vision

Atlas is a multi-user pools server. Users authenticate with Google, create or join pool groups, and answer pools published by the group administrator. A pool is private while being prepared, answerable only while open, and visible with final results after the administrator closes it.

## 2. Terminology

- **User**: a person authenticated through Google OAuth/OIDC.
- **Pool group**: a collaboration space containing members and pools.
- **Group admin**: the user who creates the group; the sole authority to manage membership and pool lifecycle in the MVP.
- **Pool**: a question with a fixed ordered set of answer options and lifecycle state `draft`, `open`, or `closed`.
- **Answer**: one user's selected option for an open pool. Each member may submit at most one answer per pool.
- **Results**: aggregate option counts and percentages, exposed to group members only after closure.

## 3. Actors

- **Unauthenticated visitor**: may begin Google sign-in and use liveness/readiness endpoints.
- **Authenticated user**: may view groups they belong to and answer open pools.
- **Group admin**: may manage membership, create/edit pools while they are drafts, open pools, and close pools.
- **Platform operator**: observes service health and security telemetry without ordinary pool content access.

## 4. MVP capabilities

1. Authenticate users through Google authorization code flow with server-side session management.
2. Create pool groups and invite or add users by verified email.
3. List and enter pool groups for which the user has membership.
4. Create and edit draft pools with a question and at least two answer options.
5. Open a draft pool so all current group members may answer.
6. Allow each group member one answer while the pool is open.
7. Close an open pool and reveal aggregate results to all group members.
8. Record membership, lifecycle, and answer mutations in an append-only audit stream.

## 5. Lifecycle invariants

- A pool starts as `draft` and is never answerable in that state.
- Only the group admin may transition `draft -> open` or `open -> closed`.
- A pool cannot be edited after it is open; a closed pool is immutable.
- Only members present in the group at answer time may answer.
- An answer is accepted only while the pool is open and only once per user.
- Answers are not returned individually to clients; aggregate results are unavailable until closure.
- Closing a pool is atomic: the state change and close audit event commit together.
- Removing a member prevents future access but does not rewrite historical audit data.

## 6. Non-goals for MVP

- Anonymous public pools, multiple administrators, weighted voting, ranked-choice answers, live result streaming, editing answers after submission, billing, file uploads, and arbitrary identity providers beyond Google.
- Hard deletion of users, groups, pools, or answer history.

## 7. Quality goals

- Python 3.12+, typed boundaries, strict linting and type checking.
- No cross-group data disclosure, including through errors, result timing, or pagination.
- WCAG 2.2 AA for sign-in, group, pool, answer, and result views.
- Google credentials and application sessions are never logged or stored in browser local storage.
- Reproducible CI and deterministic black-box contract tests.

## 8. Acceptance criteria

The implementation is complete only when authentication, group membership, pool lifecycle, one-answer enforcement, post-close result visibility, audit behavior, security controls, migrations, frontend states, and contract tests satisfy the specifications and the verifier records evidence.
