---
name: atlas-verification
description: Defines deterministic Atlas pools-server quality gates, evidence capture, and environment-failure classification.
compatibility: OpenCode verification workflow
metadata:
  domain: verification
  project: atlas
---

# Atlas Verification Skill

## Use when

Use only when reviewing a completed handoff or release candidate.

## Operating method

Verify revision and dependency inputs, then run approved lint, type, authentication/pool contract-test, migration, dependency-audit, and security gates in documented order. Capture command, exit code, stdout, stderr, duration, environment, and versions.

## Boundary rules

Verifier observes and reports only. Remediation belongs to the owning specialist; risk acceptance belongs to the architecture or security authority.

## Deterministic conventions

No interactive commands, hidden retries, network-dependent test data, bypass flags, or workspace edits. Report skipped and blocked gates distinctly.

## Edge cases

Classify missing tools, unavailable Firestore, unavailable Google OAuth test configuration, OS differences, locale/timezone drift, stale caches, package-index failures, and collection skips as environment or blocked conditions, never as passes.
