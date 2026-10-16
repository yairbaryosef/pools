---
name: atlas-frontend-qa
description: Writes Selenium UI tests for one Atlas frontend slice before implementation.
compatibility: pytest, Selenium WebDriver
metadata:
  domain: frontend
  phase: qa
---

# Frontend QA Skill

Read the approved UI slice packet. Write Selenium tests for visible behavior, keyboard/focus accessibility, API state transitions, permission visibility, validation, loading/error/empty states, and pool result privacy. Add an integration scenario against the real local backend backed by disposable SQLite; static fixtures are supplemental only. Tests run against the approved local/test target, never production. Do not implement UI code or weaken browser assertions.
