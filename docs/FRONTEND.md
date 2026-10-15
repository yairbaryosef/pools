# Frontend Interaction Specification

## 1. Screens

- **Sign-in**: explains Google sign-in, shows loading and provider failure states, and never displays raw OAuth errors or tokens.
- **My groups**: lists groups where the session has active membership and provides group creation.
- **Group detail**: shows members and pools. Admin-only controls are hidden for usability but still enforced by the API.
- **Pool editor**: admin-only draft editor for question and ordered options; prevents fewer than two options locally.
- **Open pool**: members see the question and options, one selection, submit confirmation, and answered state.
- **Closed results**: members see aggregate counts and percentages after closure; no respondent names.

## 2. State handling

Represent pool states explicitly: draft, open, and closed. Disable editing after open. Disable answer controls after a successful answer, on closure, or on a 409 response. Reconcile all mutations from server responses rather than assuming local state.

## 3. Authentication behavior

Use the server's Google redirect flow. Do not handle Google access tokens in application state or local storage. A 401 clears the session and returns the user to sign-in; 403 shows insufficient permission; 404 uses a generic inaccessible view; 409 explains lifecycle or duplicate-answer conflicts.

## 4. Accessibility and security

All controls have accessible names, keyboard focus, visible focus indicators, and live-region status announcements. Use radio-group semantics for mutually exclusive options. Render question, option labels, group names, and emails as text, never HTML. Meet WCAG 2.2 AA.
