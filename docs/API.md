# REST API Contract

## 1. General rules

- Base path: `/v1`.
- JSON media type; timestamps are RFC 3339 UTC strings.
- IDs are lowercase UUIDs. Lists use opaque cursor pagination with `limit` default 25 and maximum 100.
- Every response includes `X-Request-ID`.
- Mutating requests accept an `Idempotency-Key`.
- The browser uses an HttpOnly, Secure, SameSite application session cookie after Google callback.

## 2. Authentication endpoints

| Method | Path | Auth | Success |
|---|---|---|---|
| GET | `/auth/google/start` | none | 302 to Google with state and PKCE |
| GET | `/auth/google/callback` | Google callback | 302 to client; establishes session |
| POST | `/auth/logout` | authenticated | 204 and invalidated session |
| GET | `/auth/me` | authenticated | 200 user profile |
| GET | `/v1/users/search?username=<substring>` | authenticated | 200 bounded username suggestions |
| GET | `/healthz` | none | 200 liveness |
| GET | `/readyz` | none | 200 or 503 readiness |

The callback accepts only a verified state, PKCE verifier, approved issuer, approved client ID, and validated redirect URI. It creates or updates a user keyed by Google issuer plus subject, not by mutable email.

## 3. Pool-group endpoints

| Method | Path | Auth | Success |
|---|---|---|---|
| POST | `/v1/pool-groups` | authenticated | 201 group; creator becomes admin |
| GET | `/v1/pool-groups` | authenticated | 200 member groups |
| GET | `/v1/pool-groups/{group_id}` | member | 200 group |
| POST | `/v1/pool-groups/{group_id}/members` | admin | 201 membership |
| GET | `/v1/pool-groups/{group_id}/members` | member | 200 paginated members |
| DELETE | `/v1/pool-groups/{group_id}/members/{user_id}` | admin | 204 |

Member creation accepts exactly `{"username": value}` for an existing registered account. Username lookup uses `strip().casefold()`, matching registration uniqueness; display preserves trimmed original spelling. Usernames need not be email addresses. Missing selectors, an email selector, unknown fields, non-string or blank values, and usernames longer than 200 characters return 422 `VALIDATION_ERROR`. Unknown usernames return generic 404 `NOT_FOUND`; duplicate membership returns 409 `CONFLICT`. Membership creation/list responses include `username` where available. Authorization always uses immutable user IDs, never display names. Unregistered-account invitations are not supported.

`GET /v1/users/search?username=<substring>` requires authentication and returns `{"items":[{"username": value}]}` with at most 10 existing usernames. Matching uses trimmed case-folded substring semantics. The endpoint is available to any authenticated user because it has no group context; it exposes usernames only (never email or other profile fields), while adding a member remains admin-only.

## 4. Pool endpoints

| Method | Path | Auth | Success |
|---|---|---|---|
| GET | `/v1/pool-groups/{group_id}/pools` | member | 200 pools with member-safe state |
| POST | `/v1/pool-groups/{group_id}/pools` | admin | 201 draft pool |
| GET | `/v1/pool-groups/{group_id}/pools/{pool_id}` | member | 200 pool view |
| PATCH | `/v1/pool-groups/{group_id}/pools/{pool_id}` | admin, draft only | 200 draft pool |
| POST | `/v1/pool-groups/{group_id}/pools/{pool_id}/open` | admin | 200 open pool |
| POST | `/v1/pool-groups/{group_id}/pools/{pool_id}/close` | admin | 200 closed pool with results |
| POST | `/v1/pool-groups/{group_id}/pools/{pool_id}/answers` | member, open only | 201 answer receipt |
| GET | `/v1/pool-groups/{group_id}/pools/{pool_id}/results` | member, closed only | 200 aggregate results |

## 5. Resource shapes

User: `{id, email, display_name, avatar_url, created_at}`.

Pool group: `{id, name, admin_user_id, member_count, created_at, updated_at}`.

Membership: `{group_id, user_id, role, created_at}` where role is `admin|member`.

Pool: `{id, group_id, question, options, status, opened_at, closed_at, has_answered, created_at, updated_at}`. `has_answered` is caller-specific. Draft-only editing may include the option IDs and labels.

Results: `{pool_id, total_answers, options: [{option_id, label, count, percentage}]}`. Results never contain respondent identity.

## 6. Errors and transitions

The error envelope is `{error: {code, message, request_id, fields?}}`. Stable codes include `AUTHENTICATION_REQUIRED` 401, `FORBIDDEN` 403, `NOT_FOUND` 404, `VALIDATION_ERROR` 422, `CONFLICT` 409, `POOL_NOT_OPEN` 409, `POOL_ALREADY_ANSWERED` 409, `POOL_NOT_CLOSED` 409, `INVALID_POOL_TRANSITION` 409, `RATE_LIMITED` 429, and `INTERNAL_ERROR` 500.

Unauthorized group or pool resources return 404. Unknown JSON fields, malformed UUIDs, blank questions, fewer than two options, duplicate option IDs, and options over the documented length return 422. A second answer attempt returns 409 without revealing another user's answer.
