---
name: atlas-backend-planning
description: Plans one Atlas backend route or application slice before implementation.
compatibility: Python, FastAPI, Firestore
metadata:
  domain: backend
  phase: planning
---

# Backend Planning Skill

Read the API, PRD, authentication, data-flow, and database specifications. Produce one slice packet containing route/method, auth and role rules, request/response schemas, state transitions, repository ports, error codes, audit effects, focused test cases, dependencies, allowed paths, and forbidden paths. Do not write production code, tests, or run commands. A slice is ready only when its acceptance criteria are observable through the public API.
