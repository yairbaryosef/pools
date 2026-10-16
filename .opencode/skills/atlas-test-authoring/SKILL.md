---
name: atlas-test-authoring
description: Defines black-box pytest contract-test authoring rules derived from the Atlas pools-server specifications.
compatibility: pytest, Python 3.12+
metadata:
  domain: testing
  project: atlas
---

# Atlas Test Authoring Skill

## Use when

Use before implementation and whenever authentication, group membership, pool lifecycle, answer privacy, results, data, security, or interaction contracts change.

## Operating method

Read the relevant `docs/` specifications first. Write tests through public clients, cite observable behavior, and cover Google callback validation, session expiry, group authorization, draft/open/closed transitions, one-answer enforcement, pre-close result blocking, post-close aggregates, idempotency, pagination, safe errors, and database invariants.

## Boundary rules

Do not import private modules, inspect tables directly, assert framework internals, use external services, sleep, or weaken an oracle to fit an implementation.

## Deterministic conventions

Use fixed clocks and IDs at fixture boundaries, isolated data, stable ordering, explicit status/error assertions, and reasoned skips. A real CI target must fail when its application fixture is missing.

## Edge cases

Cover Unicode trimming, unknown fields, page limits, invalid UUIDs/cursors, cross-group isolation, duplicate keys, duplicate/late answers, invalid transitions, concurrent submissions, OAuth replay, and no-secret error bodies.
