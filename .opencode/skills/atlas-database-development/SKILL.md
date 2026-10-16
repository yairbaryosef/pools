---
name: atlas-database-development
description: Implements one SQLite persistence slice and verifies it against a disposable local SQLite database.
compatibility: Python 3.12+, sqlite3, SQLite
metadata:
  domain: database
  phase: development
---

# Database Development Skill

Read the entity packet and local SQLite QA tests. Implement only the current table, repository method, transaction, or index. Run focused tests against a unique disposable SQLite database; fix failures before continuing. All route operations must use repository persistence, never process memory. Preserve immutable answers/audits and use soft deletion where deletion is allowed. Create a focused commit after a pass when git is available. Push only with explicit approval, never force-push, never use GCP or production data.
