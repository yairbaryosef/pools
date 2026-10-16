---
name: atlas-frontend
description: Defines accessible, secure browser-client integration rules for the Atlas pools server.
compatibility: OpenCode frontend implementation
metadata:
  domain: frontend
  project: atlas
---

# Atlas Frontend Skill

## Use when

Use for Google sign-in redirects, group views, pool lifecycle views, answer forms, aggregate result views, typed transport, accessibility, and user-facing network states. Every UI slice also requires browser-to-real-backend integration against local SQLite.

## Operating method

Treat `docs/API.md`, `docs/FRONTEND.md`, and `docs/AUTHENTICATION.md` as the only client contracts. Centralize transport decoding, separate server state from form state, reconcile successful mutations from server responses, and test keyboard/focus behavior.

## Boundary rules

The client cannot grant permissions, bypass validation, infer hidden groups, expose pre-close results, or define API semantics. Never access databases, handle Google tokens, or render untrusted HTML.

## Deterministic conventions

Use stable route names, explicit query serialization, visible loading states, text-safe rendering, and a single session-expiry policy. Never persist credentials in local storage. Reconcile every mutation from the real backend response and test both unit/UI and backend integration paths.

## Edge cases

Handle 401, 403, 404, 409, 422, 429, offline states, duplicate clicks, empty groups, expired cursors, slow responses, draft/open/closed transitions, and duplicate-answer failures.
