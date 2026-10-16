---
name: atlas-security
description: Defines threat modeling, Google OAuth security, authorization, input safety, privacy, and security-gate rules for the Atlas pools server.
compatibility: Python web applications
metadata:
  domain: security
  project: atlas
---

# Atlas Security Skill

## Use when

Use for Google OAuth/OIDC validation, session security, group authorization, pool lifecycle integrity, answer privacy, input/output guardrails, logging, secrets, and security tests.

## Operating method

Threat-model every asset and trust boundary using `docs/SECURITY.md` and `docs/AUTHENTICATION.md`. Review OAuth state/nonce/PKCE, session handling, group object/action authorization, premature result disclosure, replay, injection, XSS/CSRF, leakage, exhaustion, and dependency risk.

## Boundary rules

Security may block or require evidence from any domain but cannot silently rewrite another domain's behavior or approve its own exception.

## Deterministic conventions

Classify findings as `critical`, `high`, `medium`, or `low`; cite asset, threat, control, and evidence. Missing evidence is unresolved, not safe. Treat individual answer disclosure and account takeover as high-impact findings.

## Edge cases

Review Unicode confusables, spoofed headers, duplicate headers, malformed cookies, OAuth callback replay, invalid issuer/audience/nonce, session fixation, late or duplicate answers, oversized JSON, log injection, group enumeration, and pre-close result leakage.
