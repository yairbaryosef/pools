"""Real-browser fixtures for the Atlas frontend boundary.

The default target is a child Atlas server configured with a unique, file-backed
SQLite database. The browser only crosses HTTP boundaries; the fixture never
opens the database or supplies an in-memory/fake repository. External targets
are rejected: this scoped suite must not mutate an existing listener/database.
"""
from __future__ import annotations

import os
import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT = 30.0


PASSWORD = "A-strong-browser-password-123"
def _json_request(base_url: str, path: str, payload: dict[str, str]) -> tuple[int, dict]:
    request = Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except HTTPError as exc:
        body = json.loads(exc.read() or b"{}")
        if path == "/auth/register" and exc.code == 409:
            pytest.fail(
                "BLOCKED: E2E registration collided with an existing test account; "
                f"refusing to reuse '{payload.get('username')}'"
            )
        pytest.fail(f"BLOCKED: {path} returned {exc.code}: {body}")


def _provision_accounts(base_url: str) -> dict[str, dict[str, str]]:
    """Create every browser identity through the public password API.

    Every identity is created through the public HTTP API. The owner-approved
    membership selector is the registered username. Registration does not
    produce an email address; never synthesize one for membership lookup.
    """
    # Registration is rate limited, so keep the fixture to its three identities.
    stamp = uuid4().hex
    users = {
        role: {"username": f"e2e-{role}-{stamp}", "password": PASSWORD}
        for role in ("admin", "member", "outsider")
    }
    # Keep the browser registration assertion inside the server's three-success
    # budget.  The admin is registered through the real browser fixture below;
    # the member and outsider are provisioned here for the later authenticated
    # journeys.
    for role in ("member", "outsider"):
        user = users[role]
        status, _ = _json_request(base_url, "/auth/register", user)
        assert status == 201
        opener = build_opener(HTTPCookieProcessor())
        request = Request(
            base_url.rstrip("/") + "/auth/login",
            data=json.dumps(user).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with opener.open(request, timeout=5) as response:
            assert response.status == 200
            assert json.loads(response.read()) ["username"] == user["username"]

    os.environ["ATLAS_FRONTEND_MEMBER_USERNAME"] = users["member"]["username"]
    os.environ["ATLAS_FRONTEND_MEMBER_PASSWORD"] = PASSWORD
    os.environ["ATLAS_TEST_USERS"] = json.dumps(users, sort_keys=True)
    return users


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _poll(
    url: str,
    process: subprocess.Popen[bytes] | None = None,
    log_path: Path | None = None,
) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            pytest.fail(f"BLOCKED: Atlas API exited during startup; logs: {log_path}")
        try:
            with urlopen(Request(url.rstrip("/") + "/healthz", method="GET"), timeout=1) as health:
                with urlopen(Request(url.rstrip("/") + "/", method="GET"), timeout=1) as root:
                    if health.status == 200 and root.status == 200:
                        return
        except (OSError, URLError):
            pass
        time.sleep(0.2)
    if process is None:
        pytest.fail(
            f"BLOCKED: configured ATLAS_BASE_URL did not serve /healthz and / "
            f"within {STARTUP_TIMEOUT:g}s: {url}"
        )
    pytest.fail(f"BLOCKED: Atlas API did not become ready within {STARTUP_TIMEOUT:g}s; logs: {log_path}")


@pytest.fixture(scope="session")
def atlas_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    configured_url = os.getenv("ATLAS_BASE_URL")
    if configured_url:
        pytest.fail("BLOCKED: unset ATLAS_BASE_URL; this suite requires its own disposable server")

    # Spawn the same production ASGI entrypoint used by ``npm run dev``, with a
    # unique file URL.  SQLite is intentionally file-backed so a second HTTP
    # client and a server reload observe committed state.
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_dir = tmp_path_factory.mktemp("atlas-sqlite-api")
    log_path = log_dir / "uvicorn.log"
    database_path = log_dir / f"atlas-{uuid4().hex}.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_BASE_URL": base_url,
    })
    environment.pop("ATLAS_MONGO_URI", None)
    environment.pop("ATLAS_MONGO_DATABASE", None)
    # Preserve explicitly configured real-target scenarios in the child process.
    for name, value in os.environ.items():
        if name.startswith(("ATLAS_FRONTEND_", "ATLAS_TEST_")):
            environment[name] = value
    process: subprocess.Popen[bytes] | None = None
    log_file = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "atlas.api:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        _poll(base_url, process, log_path)
        _provision_accounts(base_url)
        yield base_url
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log_file.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                database_path.with_name(database_path.name + suffix).unlink(missing_ok=True)
            except OSError:
                pass


@pytest.fixture(scope="session")
def atlas_browser(atlas_server: str) -> Iterator[tuple[webdriver.Chrome, str]]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1000")
    options.add_argument("--no-sandbox")
    try:
        driver = webdriver.Chrome(options=options)
    except WebDriverException as exc:
        pytest.fail(f"BLOCKED: Chrome/WebDriver is unavailable: {exc}")
    try:
        yield driver, atlas_server
    finally:
        driver.quit()


@pytest.fixture(scope="session")
def base_url(atlas_server: str) -> str:
    return atlas_server


@pytest.fixture(scope="session")
def browser(atlas_browser: tuple[webdriver.Chrome, str]) -> webdriver.Chrome:
    return atlas_browser[0]


def wait_for(driver: webdriver.Chrome, condition: object, timeout: float = 10) -> object:
    return WebDriverWait(driver, timeout).until(condition)  # type: ignore[arg-type]


def submit_form(driver: webdriver.Chrome, labels: dict[str, str], button: str) -> None:
    for name, value in labels.items():
        field = driver.find_element(By.NAME, name)
        field.clear()
        field.send_keys(value)
    # Auth has a tab button and a form submit button with the same label
    # ("Create account").  Targeting the form prevents Selenium from clicking
    # the tab a second time instead of submitting registration.
    driver.find_element(By.XPATH, f"//form//button[normalize-space()='{button}']").click()


def unique_username(prefix: str = "selenium") -> str:
    return f"{prefix}-{time.time_ns()}"


@pytest.fixture(scope="session")
def browser_user(browser: webdriver.Chrome, base_url: str, registered_admin: dict[str, str]) -> dict[str, str]:
    user = registered_admin
    browser.get(f"{base_url}/#/signin")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "username")))
    submit_form(browser, user, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
    return user


@pytest.fixture(scope="session")
def registered_admin(browser: webdriver.Chrome, base_url: str) -> Iterator[dict[str, str]]:
    """Register the unique admin once through the browser.

    Member and outsider are provisioned by ``_provision_accounts``.  Doing the
    admin registration here keeps the real UI assertion while using exactly
    three successful registrations from the fixture IP.
    """
    users = json.loads(os.environ["ATLAS_TEST_USERS"])
    user = users["admin"]
    browser.delete_all_cookies()
    browser.get(f"{base_url}/#/signin")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "username")))
    browser.find_element(By.XPATH, "//button[normalize-space()='Create account']").click()
    submit_form(browser, user, "Create account")
    success = wait_for(browser, EC.visibility_of_element_located((By.CSS_SELECTOR, ".success[role='status']")))
    assert success.text == f"Account {user['username']} created. Sign in to continue."
    wait_for(browser, EC.text_to_be_present_in_element((By.ID, "status"), "created"))
    yield user


@pytest.fixture
def registered_user(browser: webdriver.Chrome, base_url: str, browser_user: dict[str, str]) -> dict[str, str]:
    browser.get(f"{base_url}/#/signin")
    wait_for(browser, EC.presence_of_element_located((By.NAME, "username")))
    submit_form(browser, browser_user, "Sign in")
    wait_for(browser, EC.url_contains("#/groups"))
    yield browser_user
    browser.find_element(By.XPATH, "//button[normalize-space()='Sign out']").click()
    wait_for(browser, EC.url_contains("#/signin"))
