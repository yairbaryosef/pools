# Agent Orchestration

The executable OpenCode configuration lives under `.opencode/`. Agent definitions are `.opencode/agents/*.md`, skills are `.opencode/skills/<name>/SKILL.md`, and `opencode.json` restricts skill and task permissions. These native OpenCode files are the single source of truth for agent behavior.

The system being developed is the Atlas pools server: Google sign-in, pool groups, creator-admin membership, draft/open/closed pool lifecycle, one answer per member, aggregate results after closure, and SQLite persistence selected through `ATLAS_DATABASE_URL`. Cloud deployment is out of scope unless explicitly enabled.

The execution topology and slice state machine are defined in `docs/AGENT_ARCHITECTURE.md`. The default workflow is hierarchical: the orchestrator delegates to a domain agent, and each domain agent delegates planning, QA, and development children.

## 1. Operating order

When the prompt contains `run`, the orchestrator executes the complete
pipeline autonomously without questions or pauses: SQLite schema and
capabilities, all backend routes, then all frontend slices. Routine failures
are returned to the owning developer and rerun. The pipeline stops only for an
unrecoverable environment/safety blocker. Deployment and push remain disabled.

1. Architecture owner maintains `docs/` and resolves contradictions.
2. `DBAgent` first designs the complete SQLite relational model, constraints, indexes, transaction boundaries, efficient access patterns, and retention rules before route work begins.
3. `BackendAgent` then implements routes one by one. Each route must read/write SQLite through repositories; no route may use process memory as a source of truth.
4. `BackendAgent`, `DBAgent`, and `FrontendAgent` each run every route/capability/UI slice through planner -> QA -> developer sequentially.
5. Domain QA creates unit/contract tests before its developer starts. Database and frontend slices must additionally run integration tests; backend slices require unit/contract tests only.
6. No slice may advance until its required tests pass. A failed test returns the same slice to development; do not ask the user for routine decisions.
7. Integration QA agents verify backend↔SQLite persistence after every database slice and backend↔frontend behavior after every frontend slice.
8. Security review is opt-in only and is not invoked in the default workflow unless explicitly requested by the user.
9. `VerifierAgent` executes deterministic gates and reports raw evidence without fixing code.
10. Deployment agents are disabled by default.

## 2. Handoff packet

Every handoff includes changed paths, specification citations, assumptions, known risks, tests added/updated, and commands the verifier should run. A specialist reports `READY`, `BLOCKED`, or `NEEDS_DECISION`; no agent claims another agent's work.

Slice handoffs additionally include unit-test command/result, integration-test command/result, changed paths, assumptions, risks, commit ID when available, and push status. A developer must not start the next slice when either test class is failing. Missing tooling is an environment `BLOCKED` state; agents must diagnose and remediate it automatically where safe.

## 3. Conflict policy

API behavior in `docs/API.md` and invariants in `docs/PRD.md` win over implementation preferences. Security controls win over convenience. Unresolved ambiguity becomes a decision request; agents must not create undocumented compatibility behavior.

## 4. Verification gates

The verifier checks formatting/lint, type checking, unit/contract tests, SQLite integration tests, backend↔frontend integration tests, migration/index checks, and dependency audit in a clean environment. Backend routes require unit/contract evidence; database and frontend slices additionally require integration evidence. It classifies failures as product bug, test/spec mismatch, tool failure, missing dependency, or environment failure. It must never mark a blocked environment as a passing build.
