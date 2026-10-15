# Pool Server Architecture

## 1. Chosen shape

Atlas uses a modular monolith with ports-and-adapters boundaries. This keeps transactions and authorization close to the pool domain while allowing a later extraction of read models or background work without changing the public contract.

```text
Browser client
    | HTTPS, JSON, secure cookie or bearer token
API adapter (ASGI)
    | authentication, request validation, rate limits
Application services
    | authorization, transaction orchestration, idempotency
Domain modules
    | identity, pool group, membership, pool, answer, audit invariants
Ports
    | repositories, clock, ID generator, event publisher
Adapters
    | Local SQLite, environment configuration, observability
```

The future implementation should be organized by domain capability under `src/atlas/`, not by a single global `models/` or `utils/` bucket. Framework code must depend inward; domain code must not import an HTTP or ORM framework.

## 2. Runtime components

- **API process**: ASGI application; stateless except for database-backed sessions and pool state.
- **Google identity provider**: external OAuth/OIDC provider used only during sign-in.
- **SQLite**: source of truth for users, sessions, group membership, pools, options, answers, idempotency, and audit data during local development.
- **SQLite adapter**: server-side access through the `ATLAS_DATABASE_URL` environment setting.
- **Browser bundle**: separate client build consuming only documented endpoints.
- **Telemetry sink**: structured logs, metrics, and traces with secrets, identities, and pool payloads redacted.

## 3. Request flow

1. TLS termination forwards a request with a trusted request ID or generates one.
2. Authentication verifies the session without logging it; Google is contacted only during the callback flow.
3. Route validation parses path, query, and JSON values into typed request objects.
4. Authorization resolves the target pool group and role from server-side membership.
5. Application service executes one transaction, including an idempotency record for eligible mutations.
6. Repository writes are committed; an audit record is written in the same transaction.
7. The adapter maps domain outcomes to the API error envelope and response headers.

## 4. Dependency rules

- API adapters may call application ports, never repositories directly.
- Application services may use domain objects and ports, never database sessions directly.
- SQLite adapters own table keys, transactions, indexes, parameterized query details, and expose repository methods only.
- Security review can block any layer but cannot implement domain behavior.
- Tests in `tests/contract/` may observe the public API only; they must not inspect tables or call internal services.

## 5. Reliability and operations

Use bounded request bodies, explicit timeouts, SQLite busy/transaction limits, graceful shutdown, and health/readiness separation. Health reports process liveness; readiness verifies local SQLite without exposing connection details. Pool transitions and answers must be safe to retry when an idempotency key is supplied.
