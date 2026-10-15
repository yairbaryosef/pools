# Browser route/control coverage matrix

The primary gate is `test_complete_real_backend_browser_journey`. With no
`ATLAS_BASE_URL`, the fixtures start a local API against a unique disposable
SQLite database and launch it on a free loopback port. When `ATLAS_BASE_URL` is
provided, that user-managed target is used unchanged.

| Capability | Browser evidence |
|---|---|
| shell, health, readiness | `test_complete_real_backend_browser_journey` |
| username/password register, login, `auth/me`, logout, expiry | auth and journey tests |
| groups, detail, persistence, text safety, keyboard focus | browser and journey tests |
| members, add/remove, pagination, admin/member authorization | route-controls and journey tests |
| pool draft/edit/open/close, answers, duplicate answer, results privacy | lifecycle and journey tests |
| 401/403/404/409/422 documented errors | error-matrix and journey tests |
| idempotency, request IDs, live regions, radio semantics | journey and accessibility assertions |

The fixture creates unique member and outsider accounts through the public
`/auth/register` and `/auth/login` endpoints. The unique admin is registered
once through the real browser fixture, which preserves the registration UI
assertion while keeping the three-success per-IP budget. It then updates only
the registered member account in the disposable SQLite database with a unique
email, because the current password-registration contract has no email field
while member management resolves email. It automatically sets
`ATLAS_FRONTEND_MEMBER_EMAIL`, `ATLAS_FRONTEND_MEMBER_USERNAME`,
`ATLAS_FRONTEND_MEMBER_PASSWORD`, and `ATLAS_TEST_USERS` in the test process.

No provider-specific fixtures, pre-existing users, external fault controls, or
invented 429/500 routes are used. Those status classes remain backend-contract
coverage; browser tests use deterministic documented public behavior.

## Exact command

```powershell
pytest -q tests/frontend -m selenium
```

**Status: READY (authored; not executed in this change).** Runtime prerequisites
are Chrome/WebDriver and a writable local SQLite database. Missing
prerequisites fail explicitly rather than skip or weaken assertions.

**Citations:** `docs/API.md` §§1–6; `docs/FRONTEND.md` §§1–4;
`docs/AUTHENTICATION.md` §§11–26; `docs/SECURITY.md` §§14–21.

**Assumptions:** password registration/login are enabled by the target; the
member email update is performed only against the disposable database owned by
the local fixture; list responses expose `items` and `next_cursor`.

**Risks:** A user-managed `ATLAS_BASE_URL` whose database is not the disposable
database cannot satisfy the documented email-resolved member setup and is
reported `BLOCKED`. No production code is imported or changed.
