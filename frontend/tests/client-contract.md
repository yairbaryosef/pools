# Frontend verification notes

The browser client uses only the documented resource paths plus the server's explicit
`/auth/register` and `/auth/login` password routes. Manual browser checks should cover:

- keyboard-only sign-in, registration, group creation, radio selection, and answer submission;
- loading, empty, offline, 401/403/404/409/422/429/5xx states and visible request IDs;
- duplicate-click protection and cookie-backed reload persistence;
- draft → open → closed controls and aggregate-only closed results.

## SEC-005 browser security verification

- `node --test frontend/tests/security-contract.mjs` checks the restrictive CSP,
  referrer/permissions metadata, and the absence of inline script/style blocks,
  HTML event handlers, `innerHTML`/`outerHTML` assignment, and CSS imports.
- The CSP allows only same-origin module scripts, stylesheet, API connections,
  and same-origin images. The client uses no inline script or style.
- Deployment evidence is still required: serve the equivalent CSP as an HTTP
  response header, including `frame-ancestors 'none'` (which is not enforced
  from a meta element), plus `X-Content-Type-Options: nosniff` and
  `Strict-Transport-Security` on HTTPS. These headers are outside frontend-owned
  paths and are not claimed by this test.
