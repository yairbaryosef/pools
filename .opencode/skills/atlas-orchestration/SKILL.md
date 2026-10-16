---
name: atlas-orchestration
description: Coordinates Atlas pools-server specialist agents, specification handoffs, ownership boundaries, and deterministic release gates.
compatibility: OpenCode project configuration
metadata:
  domain: orchestration
  project: atlas
---

# Atlas Orchestration Skill

## Autonomous `run` mode

When the user prompt contains the word `run`, execute the complete pipeline
without asking questions, waiting for routine approval, or stopping between
 domains. Run SQLite entity design and persistence first, then every backend
route, then every frontend slice. Use planner -> QA -> developer for every
capability, route, and UI slice. Require database unit plus local-SQLite
integration tests, backend unit/contract tests, and frontend Selenium plus
backend integration tests. On failure, return the same slice to its developer,
fix it, and rerun; never skip a failing gate or weaken an oracle.

Stop only for an unrecoverable environment failure after safe remediation,
missing authoritative specifications, data-loss risk, or an explicit safety
boundary. Never deploy, access production, expose credentials, mutate remote
cloud resources, or push. Local commits are optional when git tooling permits;
push always requires explicit approval.

## Use when

Use this skill for any multi-agent Atlas pools-server task or release decision. The default persistence target is a disposable local SQLite database configured by `ATLAS_DATABASE_URL`; do not substitute GCP services. Backend slices require unit/contract tests; integration gates apply only to database and frontend slices.

## Operating method

Read `docs/ORCHESTRATION.md` first. Create a scoped task packet, assign exactly one owner, require specification citations, and collect a structured handoff before assigning dependent work. In `run` mode execute SQLite DBAgent capabilities, BackendAgent route slices, and FrontendAgent UI slices sequentially. After every database/frontend slice require integration QA against the adjacent boundaries. Security is opt-in only. Require evidence for Google login, group membership, pool lifecycle, one-answer enforcement, post-close results, SQLite persistence, and browser/API integration.

## Boundary rules

No agent edits another agent's owned artifacts. Security can block any change. Verifier observes and reports only. The orchestrator resolves ambiguity but does not invent undocumented behavior.

## Deterministic conventions

Use statuses `READY`, `BLOCKED`, and `NEEDS_DECISION` for specialists and `PASS`, `BLOCKED`, and `FAIL` for verification. Every handoff includes changed paths, citations, tests, assumptions, and risks.

## Edge cases

Treat missing dependencies, SQLite initialization failures, test collection skips, and tool errors as environment or blocked states, never as passes. Agents must attempt safe automatic remediation (install declared packages, create an isolated SQLite database) before reporting blocked. Do not stop for routine ambiguity; resolve from the specifications and preserve documented behavior. In `run` mode continue automatically after every READY handoff and feed failures back to the owning developer.
