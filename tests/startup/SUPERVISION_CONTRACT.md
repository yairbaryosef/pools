# Launcher supervision regression handoff

Contract source: requested confirmed Windows `os.execv` regression. Neither
deployment document currently specifies local process supervision; do not treat
the cloud deployment instructions as permission to deploy or use credentials.

Specification citations:
- `docs/ORCHESTRATION.md:21`: QA contracts precede implementation.
- `docs/ORCHESTRATION.md:25,30-32`: verifier owns execution evidence and handoffs.
- `docs/ORCHESTRATION.md:5`: SQLite configuration via `ATLAS_DATABASE_URL`.
- `docs/DEPLOYMENT.md:24,29`: smoke gates and credential isolation.
- Baseline `scripts/dev.py:81,96-116`: interpreter/server replacement bug;
  `:18,64-66,83-87`: explicit database configuration remains authoritative.

## Developer coordination

Use simple foreground subprocess supervision, not `os.execv`, for both server
launch and interpreter handoff. Wait for the owned child and propagate its exit
code. On interrupt, stop/wait for the owned child, never enumerate or kill owners
of port 8000. Clean interrupt status is 0 or conventional 130. An occupied port
must produce a nonzero exit and a clear diagnostic naming 8000. Explicit invalid
DB settings must reach validation unchanged, rather than silently selecting a
default database.

## Inventory / fixture contract

`test_dev_supervision.py`: four foreground/exit/DB parameter cases, one interrupt
case, one occupied-port case. Runs the copied public CLI with a controlled
`uvicorn` module as its external subprocess dependency. IPC uses bounded blocking
sockets and process waits, not sleeps. Temporary checkout includes only the
launcher, conflicting nonsecret `.env`, and probe. No application internals are
imported. Cleanup cooperatively releases the probe; fallback termination targets
only the launcher handle owned by the test. No user processes are killed.

Run on Windows with project Python 3.12+:

```
python -m pytest tests/startup/test_dev_supervision.py -q
python -m pytest tests/startup -q
python -m ruff check tests/startup/test_dev_supervision.py
```

Execution results: not run by TestWriterAgent (no execution tool available;
verifier owns verdicts). Baseline is expected to fail the supervision contract;
this is a prediction, not a recorded red run.

Intentional skips: none. Occupied real port 8000 or unsupported Python fails
explicitly as an environment blocker, never passes/skips silently.

Risks / requirements not established by this fixture: real Uvicorn reload-tree
cleanup, npm-to-Python console event propagation, old-Python interpreter handoff,
real application health/readiness/register, and DB persistence. Windows verifier
must exercise those separately in an isolated environment; this probe creates no
reload grandchildren. Windows CTRL_BREAK delivery requires an attached console.
POSIX execution covers the portable contract but cannot prove the Windows bug
fixed. The unrelated listener oracle demonstrates continued ownership, not a
global guarantee against all process-enumeration behavior.
