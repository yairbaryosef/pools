# Hierarchical Agent Architecture

## 1. Topology

```text
atlas-orchestrator (primary)
├── atlas-backend
│   ├── atlas-backend-planner
│   ├── atlas-backend-qa
│   └── atlas-backend-developer
├── atlas-database
│   ├── atlas-database-planner
│   ├── atlas-database-qa
│   └── atlas-database-developer
├── atlas-database-integration
└── atlas-frontend
    ├── atlas-frontend-planner
    ├── atlas-frontend-qa
    └── atlas-frontend-developer
```

`atlas-database-integration` and `atlas-backend-frontend-integration` are test-only specialists. Backend routes do not have a separate integration stage. `atlas-gcp-deployment` exists as an optional deployment specialist but is not part of the default workflow. No agent deploys the application.

## 2. Responsibility layers

- **Primary orchestrator**: orders domain work, resolves cross-domain contracts, and starts one domain workflow at a time.
- **Domain agent**: owns the domain workflow and delegates only to its planner, QA, and developer children.
- **Planner**: decomposes one route, data capability, or UI slice into an implementation contract. It does not implement or execute tests.
- **QA agent**: writes unit/contract tests before development and reports the test oracle. It does not implement production code.
- **Integration QA agent**: writes and runs real boundary tests against disposable local SQLite and the neighboring API/UI boundary. It does not weaken unit tests or implement production behavior.
- **Developer agent**: implements one slice, runs only its slice tests, fixes failures, and produces a handoff. It does not expand scope.

## 3. Slice state machine

```text
UNPLANNED -> PLANNED -> TESTED -> IN_PROGRESS -> VERIFIED -> COMMITTED
                                  \-> FAILED -> IN_PROGRESS
```

1. Planner creates a slice packet with route/UI name, requirements, dependencies, acceptance criteria, allowed paths, and forbidden paths.
2. QA turns the packet into unit/contract tests before developer work begins.
3. Developer implements only that slice and runs the slice tests.
4. Integration QA runs after implementation against disposable local SQLite and the adjacent boundary. A failed unit or integration test sends the same developer back to `IN_PROGRESS`.
5. A passing slice is reviewed for scope and then committed when git tooling is available. Push is always approval-gated; no agent pushes automatically.
6. The domain agent starts the next slice only after unit and integration tests pass. Commit is required when git tooling is available; push always remains approval-gated.

## 4. Backend workflow

Backend slices are API routes or closely coupled application operations. QA uses repository ports for deterministic unit/contract tests. Developer runs the focused unit/contract suite before moving on; no separate backend integration suite is required.

## 5. Database workflow

Database slices are SQLite table/constraint/index/transaction capabilities. QA uses a unique disposable SQLite file per run. Developer verifies persistence, transaction/uniqueness, group isolation, cleanup, and rereads against local SQLite. No application deployment occurs.

## 6. Frontend workflow

Frontend slices are user-visible UI parts such as Google sign-in, group list, pool editor, answer form, and results view. QA writes Selenium and backend-integration tests covering behavior, accessibility, API-visible state, and local SQLite persistence. Developer runs both focused suites against the approved local/test target, fixes failures, and commits only when both pass.

## 7. Git checkpoint policy

The target remote is `https://github.com/yairbaryosef/pools.git`. Each verified slice creates a focused commit before the next slice begins. Push is explicit and approval-gated; agents must inspect status, avoid unrelated files, never force-push, and stop on a dirty or conflicting worktree. The orchestrator does not push automatically.

## 8. Deployment policy

The GCP deployment agent is not invoked by default. Verification may validate artifacts, but cloud traffic changes, image deployment, and production smoke tests require a separate explicit request.
