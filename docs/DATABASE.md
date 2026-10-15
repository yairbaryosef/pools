# SQLite Database Specification

## 1. Runtime and configuration

SQLite is the approved persistence target. The application requires
`ATLAS_DATABASE_URL` with a `sqlite:///...` URL; a file-backed database is the
normal runtime target and `sqlite:///:memory:` is suitable only for isolated
tests. The connection is server-only and must not contain credentials. Tests
use a unique disposable SQLite file and never production data.

The adapter enables foreign keys and a busy timeout, bootstraps the schema
idempotently, and uses `BEGIN IMMEDIATE` for application transactions. No
process-local store is a source of truth.

## 2. Relational model

All IDs are lowercase UUID strings and timestamps are RFC 3339 UTC strings.

- `users`: `id`, Google `google_issuer`/`google_subject`, email fields, profile
  fields, `created_at`, and `updated_at`. Partial unique indexes enforce the
  immutable Google identity and normalized email (and optional username).
- `sessions`: `id`, `user_id`, `token_hash`, timestamps, and nullable
  `revoked_at`; only the token hash is stored.
- `pool_groups`: `id`, `name`, `admin_user_id`, and timestamps.
- `memberships`: `(group_id, user_id)` primary key, `role`, timestamps, and
  nullable `removed_at`. Removal is a soft delete.
- `pools`: `id`, `group_id`, `question`, `status`, JSON-encoded ordered
  `options_json`, lifecycle timestamps, and creation/update timestamps.
- `answers`: `(pool_id, user_id)` primary key, `option_id`, and
  `submitted_at`. There is no public update or delete operation.
- `idempotency`: `scope_key` primary key, principal/group, method/route,
  request hash, response metadata, and creation/expiry timestamps.
- `audit_events`: append-only integer ID, group and actor IDs, request ID,
  action, entity type/ID, JSON metadata, and occurrence time.
- `abuse_control`: expiring `(bucket, key)` counters used by rate limiting.

Foreign keys connect memberships, pools, answers, and sessions to their
parents. Options remain a serialized ordered snapshot on the pool so opened
and closed pools cannot change their choices.

## 3. Isolation and indexes

Every group-scoped repository method receives `group_id` explicitly and uses
SQL predicates joining the target group. Callers cannot compose SQL or table
names. Required indexes include active session lookup, user membership lookup,
`pools(group_id, status, created_at, id)`, idempotency expiry, and abuse-counter
expiry. Cursor pagination uses validated `(created_at, id, group_id, status)`
values and deterministic tie-breakers.

The composite answer primary key enforces one answer per user and pool at the
database boundary. Unique user identity indexes and the membership primary key
provide the corresponding identity and duplicate-membership invariants.

## 4. Transaction requirements

Pool open and close transactions read the canonical pool, verify state and
admin identity, update lifecycle fields, and insert the audit event atomically.
Answer submission verifies an open pool and active membership, validates the
option from the pool snapshot, inserts the answer, and inserts audit data in
one transaction. A primary-key conflict maps to `POOL_ALREADY_ANSWERED`.

Do not perform network calls inside transactions. Handle SQLite busy/locking
errors explicitly; do not rely on process-local locks. Rollbacks must leave no
partial lifecycle, answer, idempotency, or audit write. Audit and answer rows
are immutable and are never hard-deleted in the MVP.

## 5. Security rules

SQLite is server-only; browsers never receive database access. Use parameterized
SQL, bounded result sets, explicit group predicates, and least-privilege file
permissions. Readiness checks the local SQLite connection without exposing its
path or contents.
