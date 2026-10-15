# Pool Server Security Threat Model

## 1. Assets and trust boundaries

Assets include Google identity assertions, session tokens, user email addresses, group membership, pool questions/options, answers, aggregate results, and audit history. Trust boundaries are browser-to-API, API-to-Google, API-to-local SQLite file, and observability output. The SQLite file and its filesystem permissions are server-side trust-boundary assets; browser data and all incoming headers are untrusted.

## 2. Required controls

| Threat | Required control | Verification |
|---|---|---|
| OAuth login CSRF | state, nonce, PKCE, exact redirect URI, issuer/audience validation | auth contract tests |
| Account takeover | immutable Google subject identity, verified email policy, hashed sessions, revocation | security review |
| Session theft | HttpOnly, Secure, SameSite cookie, rotation/revocation, no token logs | configuration tests |
| Broken group authorization | active membership and role check on every group/pool request | cross-group tests |
| Premature result disclosure | block result counts until closed; never expose answer rows | lifecycle tests |
| Duplicate or late answers | server state check and `(pool_id,user_id)` uniqueness | concurrency tests |
| Answer privacy leakage | aggregate results only, no respondent identity, redacted audit metadata | response tests |
| Pool tampering | admin-only lifecycle, draft-only edits, row ownership checks | authorization tests |
| CSRF | SameSite cookies plus origin/CSRF strategy for cookie mutations | mutation tests |
| Injection/XSS | parameterized queries, bounded input, text rendering, CSP | static and boundary tests |
| Resource exhaustion | body, question, option, page, session, and rate limits | limit tests |

## 3. Google OAuth rules

Use authorization code flow with PKCE. Validate `iss`, `aud`, `sub`, `email`, `email_verified`, `exp`, state, nonce, and redirect URI. Never trust a client-provided email as identity. Store only the minimum Google profile data required by the product.

## 4. Privacy and logging

Do not log OAuth codes, ID tokens, session cookies, raw answer payloads, or full Google responses. Ordinary audit events record lifecycle actions and actor IDs but not selected option content. Results contain counts only.

## 5. Abuse and incidents

Rate-limit OAuth starts/callbacks, login failures, group creation, member additions, pool opening/closing, and answer submission. Correlate requests without exposing group content. Revoke sessions and rotate provider/application secrets after compromise.
