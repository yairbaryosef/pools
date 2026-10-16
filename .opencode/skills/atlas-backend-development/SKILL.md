---
name: atlas-backend-development
description: Implements one tested Atlas backend route at a time and fixes its focused test failures.
compatibility: Python 3.12+, FastAPI, Firebase Admin SDK
metadata:
  domain: backend
  phase: development
---

# Backend Development Skill

Read the slice packet and focused QA tests. Implement only the current route and its required application/repository ports. Run the focused test set after implementation; fix every failure against the documented contract, then perform a scope review. Create a focused commit only after tests pass. Push only after explicit approval, never force-push, and never include unrelated files.
