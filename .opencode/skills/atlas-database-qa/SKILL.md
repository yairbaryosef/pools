---
name: atlas-database-qa
description: Writes SQLite database contract tests against a local disposable test database.
compatibility: pytest, sqlite3, local SQLite
metadata:
  domain: database
  phase: qa
---

# Database QA Skill

Read the approved database slice packet. Write deterministic tests against a unique disposable SQLite database, never a mock or remote production service. Cover relational-key isolation, transactions, rollback, one-answer uniqueness, lifecycle states, bounded queries, audit writes, rereads, and cleanup. Tests must fail closed when SQLite cannot be initialized and must not silently fall back to an in-memory fake.
