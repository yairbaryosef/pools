---
name: atlas-backend-qa
description: Writes focused black-box backend tests against mocked Firestore ports before route implementation.
compatibility: pytest, FastAPI, mock Firestore repositories
metadata:
  domain: backend
  phase: qa
---

# Backend QA Skill

Read the approved backend slice packet. Write deterministic public API tests using mocked Firestore/repository ports, never GCP credentials or production data. Cover success, auth, role checks, validation, idempotency, lifecycle conflicts, tenant/group isolation, audit effects, and safe errors. Do not implement production code or weaken assertions. Report the focused test command and oracle.
