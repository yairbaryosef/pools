# Authentication Specification

## Provider

The MVP uses Google OAuth 2.0 authorization code flow with OpenID Connect and PKCE. The server, not the browser, exchanges the code and validates the ID token. Configuration includes issuer, client ID, client secret, exact redirect URI, and approved frontend origin.

## Account identity

The immutable account key is `(issuer, subject)`. Email is required and must be verified by Google for account creation. A changed Google email updates the profile only after provider claims are validated; it never creates a second account for the same subject.

## Session

After successful callback validation, issue a cryptographically random opaque session token. Persist only its hash, user ID, expiry, creation time, last-seen time, and revocation state. Send the raw token only as an HttpOnly, Secure, SameSite cookie. Logout revokes the session.

## Flow requirements

1. Generate state, nonce, and PKCE verifier server-side.
2. Store the short-lived flow record bound to state and browser session context.
3. Redirect to Google with exact scopes needed for identity and email.
4. Verify callback state and exchange the code once.
5. Validate issuer, audience, nonce, subject, email verification, expiry, and redirect URI.
6. Upsert the user and issue a session.
7. Redirect to an allowlisted frontend URL without tokens in query parameters.

## Failure behavior

Invalid, expired, reused, or mismatched callbacks return a generic authentication failure and do not reveal provider details. Callback records are single-use and expire quickly. The API returns `401 AUTHENTICATION_REQUIRED` for absent, revoked, or expired sessions.
