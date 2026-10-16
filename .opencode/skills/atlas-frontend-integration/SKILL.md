---
name: atlas-frontend-integration
description: Defines browser-to-backend integration testing against local SQLite.
compatibility: Selenium, FastAPI, local SQLite
metadata:
  domain: integration
  project: atlas
---

# Atlas Frontend Integration Skill

Use after each focused Selenium UI slice. Run the actual local backend against a unique disposable SQLite database and drive the browser through documented routes. Verify mutation rereads, permissions, lifecycle state, one-answer enforcement, aggregate-result privacy, loading/error states, and accessibility. A static fixture is supplemental only. Never store credentials in the browser, use production, deploy, or push. Capture raw browser/API/database evidence and classify failures.
