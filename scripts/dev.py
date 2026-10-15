"""Launch the local Atlas API with the repository's development environment."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path


def _load_local_environment(env_file: Path) -> None:
    """Best-effort load of the optional local environment.

    ``npm run dev`` is also useful in a clean checkout, where there is no
    ``.env`` file and the launcher must not depend on python-dotenv merely to
    start. A malformed convenience file must not block the file-backed local
    SQLite default. Explicit shell variables remain authoritative through
    ``override=False``; readable values are validated during composition.
    """
    if not env_file.is_file():
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    except Exception:
        # A local convenience file must not prevent startup. Explicit invalid
        # values are still rejected by SQLiteSettings.from_env.
        return


def _clear_source_bytecode(root: Path) -> None:
    """Remove bytecode for the source trees before starting the reloader.

    A reload child can otherwise import a stale ``.pyc`` left by a different
    interpreter (the repository has historically been run with both Python
    3.8 and 3.12).  Source is authoritative for this development launcher.
    """
    for source_root in (root / "src", root / "scripts"):
        for cache in source_root.rglob("__pycache__"):
            if cache.is_dir():
                shutil.rmtree(cache)


def _python_for_project(root: Path) -> str:
    """Choose a supported project interpreter, not an unrelated PATH Python."""
    if sys.version_info >= (3, 12):  # noqa: UP036 - bootstrap may run on older Python
        return sys.executable
    for candidate in (
        root / ".venv312" / "Scripts" / "python.exe",
        root / ".venv312" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Atlas requires Python 3.12+; no project interpreter was found")


def _ensure_local_database_url(root: Path) -> None:
    """Export the same safe default used by production composition.

    This happens before Uvicorn imports ``atlas.api``.  Thus the reload child
    and the initial process see identical configuration, while an explicitly
    supplied non-blank value remains untouched for SQLiteSettings to validate.
    """
    if not os.environ.get("ATLAS_DATABASE_URL", "").strip():
        os.environ["ATLAS_DATABASE_URL"] = f"sqlite:///{root / 'database' / 'atlas-dev.sqlite3'}"


def _check_port() -> None:
    """Check availability without connecting to or disturbing an existing owner."""
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError as exc:
            raise RuntimeError(
                "Atlas cannot start: port 8000 is occupied/in use or unavailable; "
                "the existing listener has been left untouched."
            ) from exc


def _supervise(command: list[str]) -> int:
    """Remain in the foreground and forward interrupts only to our child group."""

    def interrupted(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signals = [signal.SIGINT, signal.SIGTERM]
    if os.name == "nt":
        signals.append(signal.SIGBREAK)
    previous = {sig: signal.signal(sig, interrupted) for sig in signals}
    child = None
    try:
        child = subprocess.Popen(  # noqa: S603 - explicit interpreter, no shell
            command,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        # Windows' unbounded process wait can defer Python signal handlers
        # indefinitely. Periodically return to Python so Ctrl+Break reaches
        # the cleanup below while the server is still running.
        while True:
            try:
                return child.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        # A second console event must not abandon cleanup halfway through.
        for sig in signals:
            signal.signal(sig, signal.SIG_IGN)
        if child is not None and child.poll() is None:
            try:
                if os.name == "nt":
                    child.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(child.pid, signal.SIGINT)
                child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                if os.name == "nt":
                    # Target only the process tree rooted at our Popen handle,
                    # never discover PIDs by port or executable name.
                    if child.poll() is None:
                        subprocess.run(  # noqa: S603 - owned PID only, no shell
                            [
                                str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                                "/PID",
                                str(child.pid),
                                "/T",
                                "/F",
                            ],
                            check=False,
                            capture_output=True,
                        )
                else:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait(timeout=5)
        return 130
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    # Select the supported interpreter before importing optional launcher
    # dependencies.  A system Python 3.8 may not have python-dotenv installed,
    # while the project's 3.12 environment does.
    python = _python_for_project(root)
    _check_port()
    if Path(sys.executable).resolve() != Path(python).resolve():
        return _supervise([python, str(Path(__file__).resolve()), *sys.argv[1:]])
    # Keep an explicitly supplied database URL authoritative.  The local
    # application composition supplies a safe SQLite file when neither the
    # shell nor .env configures one. Export it before Uvicorn imports app.
    _load_local_environment(root / ".env")
    _ensure_local_database_url(root)
    _clear_source_bytecode(root)

    src = root / "src"
    # Do not inherit another checkout/site installation: that is how an old
    # atlas.database.sqlite can win over the current source tree.
    os.environ["PYTHONPATH"] = str(src)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    return _supervise(
        [
            python,
            "-B",
            "-m",
            "uvicorn",
            "atlas.api:app",
            "--app-dir",
            str(src),
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--reload",
            "--reload-dir",
            str(src),
            "--reload-dir",
            str(root / "frontend"),
        ],
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Atlas launcher: {exc}", file=sys.stderr)
        sys.exit(1)
