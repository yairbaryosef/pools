---
name: atlas-backend
description: Defines Python application-layer and REST API implementation rules for the Atlas pools server.
compatibility: Python 3.12+, FastAPI, Pydantic
metadata:
  domain: backend
  project: atlas
---

# Atlas Backend Skill

## Use when

Use for Google callback handling, session services, pool-group membership, pool lifecycle, answer submission, result aggregation, REST adapters, DTOs, validation, errors, and backend wiring. Every route requires deterministic unit/contract coverage; database and frontend integration coverage is owned by their respective domains.

## Operating method

Derive behavior from `docs/API.md`, `docs/PRD.md`, `docs/AUTHENTICATION.md`, `docs/ARCHITECTURE.md`, and `docs/DATA_FLOWS.md`. Keep adapters thin, use explicit ports, enforce group membership and admin authorization in application services, and map failures to stable error envelopes.

## Boundary rules

Handlers call application ports only. Application services call domain code and ports only. Domain code cannot import FastAPI, Firebase Admin SDK, OAuth SDKs, or transport concerns. Do not author Firestore indexes or browser code.

## Deterministic conventions

Use Python 3.12+, type annotations, timezone-aware UTC datetimes, explicit status/error mappings, bounded parsing, and one request ID per request. Make `draft -> open -> closed` transitions explicit and transactional. No global mutable state or hidden dependency injection. Keep integration fixtures disposable and never use remote production services.

## Edge cases

Reject unknown fields, blank questions, fewer than two options, malformed UUIDs, oversized bodies, invalid cursors, cross-group IDs, unauthenticated Google callbacks, duplicate idempotency fingerprints, late answers, duplicate answers, and invalid pool transitions.
