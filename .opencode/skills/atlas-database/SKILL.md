---
name: atlas-database
description: Defines SQLite modeling, transaction, index, and group-isolation rules for the Atlas pools server.
compatibility: Python 3.12+, stdlib sqlite3, local SQLite
metadata:
  domain: database
  project: atlas
---

# Atlas Database Skill

## Use when

Use for SQLite schema, indexes, transaction boundaries, repository adapters,
session persistence, pool lifecycle, answer uniqueness, and group isolation.
Design the relational model and efficient access patterns before implementing
route-specific persistence.

## Operating method

Derive every table, constraint, and invariant from `docs/DATABASE.md`,
`docs/DATA_FLOWS.md`, and `docs/AUTHENTICATION.md`. Use explicit relational
tables, primitive string IDs, bounded result sets, deterministic ordering, one
answer per user and pool, and local transaction/index safety.

## Boundary rules

Repositories expose typed ports; callers cannot receive database connections or
compose SQL statements. Domain policy remains in application services even
when a SQL transaction also protects it.

## Deterministic conventions

Use lowercase snake_case columns, canonical lowercase UUID strings, UTC
timestamps, foreign keys, declared SQLite indexes, unique cursor tie-breakers,
and immutable answer/audit rows. Route reads and writes must go through SQL
repositories, never process memory. Use soft deletion for removable
memberships and preserve historical records. Never interpolate identifiers or
values into SQL.

## Edge cases

Handle duplicate membership, removed members, invalid pool options, concurrent
open/close operations, concurrent answer inserts, session expiry, cursor
tampering, transaction rollback, SQLite locking/busy behavior, schema drift,
and audit preservation.
