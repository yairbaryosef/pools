---
name: atlas-database-planning
description: Plans one SQLite table, index, or transaction capability before implementation.
compatibility: Local SQLite, Python sqlite3
metadata:
  domain: database
  phase: planning
---

# Database Planning Skill

Read the SQLite database, data-flow, security, and API specifications. Produce one capability packet with table relationships, columns/constraints, primitive string keys, access/query patterns, indexes, group isolation predicates, transaction read/write set, rollback behavior, retention/soft-delete rules, disposable test database, allowed paths, and forbidden paths. Do not implement or execute commands. Never plan an in-memory fallback or remote cloud target.
