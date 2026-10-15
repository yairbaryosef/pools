"""CLI regression contract: user-requested Windows foreground supervision.

See docs/ORCHESTRATION.md:21,25,30 and docs/DEPLOYMENT.md:24,29.
The subprocess dependency is substituted, not the launcher's implementation.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 10

# A cooperative subprocess fixture: no application imports, DB access, reload
# trees, credentials, sleeps, process enumeration, or arbitrary PID termination.
SERVER = '''\
import json
import os
import signal
import socket
import sys
import time

control = socket.create_connection(("127.0.0.1", int(os.environ["PROBE_PORT"])), 10)
stream = control.makefile("rwb", buffering=0)
def report(value):
    stream.write((json.dumps(value) + "\\n").encode())
def interrupted(signum, frame):
    report({"event": "interrupted"})
    sys.exit(0)
signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, interrupted)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, interrupted)
report({"event": "started", "pid": os.getpid(),
        "database": os.environ.get("ATLAS_DATABASE_URL"), "argv": sys.argv[1:]})
if os.environ.get("PROBE_BIND") == "1":
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 8000))
    except OSError:
        print("ERROR: address already in use: 127.0.0.1:8000", file=sys.stderr)
        sys.exit(1)
    else:
        listener.close()
        sys.exit(0)
# Windows can defer Python signal handlers during a blocking socket read.
# Return to Python within the launcher's graceful-shutdown deadline, without
# sleeps or retrying a makefile read after timeout (which poisons its buffer).
control.settimeout(0.2)
deadline = time.monotonic() + 10
received = bytearray()
while b"\\n" not in received:
    if time.monotonic() >= deadline:
        raise TimeoutError("probe received no command within 10 seconds")
    try:
        chunk = control.recv(4096)
    except socket.timeout:
        continue
    if not chunk:
        raise RuntimeError("probe control channel closed before a command")
    received.extend(chunk)
command = json.loads(bytes(received).split(b"\\n", 1)[0])
sys.exit(command["exit"])
'''


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Copy only the public entrypoint; never load the real checkout's .env."""
    if sys.version_info < (3, 12):
        pytest.fail("Launcher regression target requires the project Python 3.12+")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "frontend").mkdir()
    shutil.copyfile(ROOT / "scripts" / "dev.py", tmp_path / "scripts" / "dev.py")
    (tmp_path / "src" / "uvicorn.py").write_text(SERVER, encoding="utf-8")
    (tmp_path / ".env").write_text(
        "ATLAS_DATABASE_URL=sqlite:///must-not-win.sqlite3\n", encoding="utf-8"
    )
    return tmp_path


@contextmanager
def launcher(checkout: Path, database: str, *, bind: bool = False):
    """Own every created handle; stop the probe cooperatively even on failure."""
    with socket.socket() as rendezvous:
        rendezvous.bind(("127.0.0.1", 0))
        rendezvous.listen()
        rendezvous.settimeout(TIMEOUT)
        # Deliberately do not propagate OAuth/session/cloud secrets.
        env = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
        }
        env.update(
            ATLAS_DATABASE_URL=database,
            PROBE_PORT=str(rendezvous.getsockname()[1]),
            PROBE_BIND="1" if bind else "0",
            PYTHONPATH=str(checkout / "src"),
        )
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with (checkout / "output.log").open("w+b") as output:
            process = subprocess.Popen(  # noqa: S603 - fixed copied entrypoint
                [sys.executable, "-B", str(checkout / "scripts" / "dev.py")],
                cwd=checkout, env=env, stdout=output, stderr=output,
                creationflags=flags,
            )
            connection = None
            stream = None
            try:
                # Occupancy can be rejected before spawning the dependency.
                if bind:
                    yield process, None, None, output
                else:
                    connection, _ = rendezvous.accept()
                    connection.settimeout(TIMEOUT)
                    stream = connection.makefile("rb")
                    started = json.loads(stream.readline())
                    yield process, connection, (started, stream), output
            finally:
                if connection is None:
                    rendezvous.settimeout(0.1)
                    try:
                        connection, _ = rendezvous.accept()
                    except TimeoutError:
                        pass
                if connection is not None:
                    try:
                        connection.sendall(b'{"exit": 0}\n')
                    except OSError:
                        pass
                if stream is not None:
                    stream.close()
                if connection is not None:
                    connection.close()
                try:
                    process.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    # Only the Popen handle created here, never a port/PID lookup.
                    process.terminate()
                    process.wait(timeout=TIMEOUT)


@pytest.mark.parametrize("exit_code", [0, 7])
@pytest.mark.parametrize(
    "database", ["sqlite:///explicit.sqlite3", "invalid-explicit-setting"]
)
def test_foreground_supervisor_preserves_database_and_child_exit(
    checkout: Path, database: str, exit_code: int
) -> None:
    with launcher(checkout, database) as (process, connection, probe, _):
        started, _ = probe
        assert started["event"] == "started"
        assert started["pid"] != process.pid, "launcher replaced itself instead of supervising"
        assert started["database"] == database, "explicit DB value was silently replaced"
        assert "atlas.api:app" in started["argv"]
        assert "--reload" in started["argv"]
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.25)
        connection.sendall(json.dumps({"exit": exit_code}).encode() + b"\n")
        assert process.wait(timeout=TIMEOUT) == exit_code


def test_interrupt_stops_owned_server_and_does_not_touch_unrelated_owner(
    checkout: Path,
) -> None:
    # A separate listening owner must remain untouched throughout interruption.
    with socket.socket() as unrelated:
        unrelated.bind(("127.0.0.1", 0))
        unrelated.listen()
        unrelated.settimeout(TIMEOUT)
        with launcher(checkout, "sqlite:///explicit.sqlite3") as (process, _, probe, _):
            started, stream = probe
            assert started["pid"] != process.pid
            assert process.poll() is None
            interrupt = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT
            process.send_signal(interrupt)
            assert json.loads(stream.readline()) == {"event": "interrupted"}
            assert stream.readline() == b"", "owned server did not close its control channel"
            assert process.wait(timeout=TIMEOUT) in (0, 130), "interrupt must exit cleanly"
            with socket.create_connection(unrelated.getsockname(), TIMEOUT) as client:
                peer, _ = unrelated.accept()
                with peer:
                    client.sendall(b"still-owned")
                    assert peer.recv(11) == b"still-owned"


def test_occupied_port_fails_clearly_without_displacing_owner(checkout: Path) -> None:
    with socket.socket() as owner:
        if os.name == "nt":
            owner.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            owner.bind(("127.0.0.1", 8000))
        except OSError as exc:
            pytest.fail(f"Environment blocked: port 8000 already owned; leave it untouched: {exc}")
        owner.listen()
        owner.settimeout(TIMEOUT)
        with launcher(checkout, "sqlite:///explicit.sqlite3", bind=True) as launched:
            process, _, _, log = launched
            assert process.wait(timeout=TIMEOUT) != 0
            log.seek(0)
            diagnostic = log.read().decode("utf-8", errors="replace").lower()
            assert "8000" in diagnostic
            assert "in use" in diagnostic or "occupied" in diagnostic
            assert "traceback" not in diagnostic
            with socket.create_connection(("127.0.0.1", 8000), TIMEOUT) as client:
                peer, _ = owner.accept()
                with peer:
                    client.sendall(b"owner")
                    assert peer.recv(5) == b"owner"
