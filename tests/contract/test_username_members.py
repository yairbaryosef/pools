"""Owner-approved username membership delta; API §§3/6, PRD §4, SECURITY §2.

These tests own a disposable SQLite server, never an externally supplied target.
The selector/username response assertions are expected red before implementation.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from .conftest import create_group, create_pool, require_error, require_status

pytestmark = pytest.mark.contract
PASSWORD = "Username-contract-password-123"


def mutate(client, path, body=None, *, method="POST"):
    return client.request(method, path, json=body,
                          headers={"Idempotency-Key": str(uuid4())})


@pytest.fixture
def username_accounts(tmp_path):
    """Three publicly registered accounts; no email synthesis or private imports."""
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": str(root / "src"),
        "ATLAS_DATABASE_URL": f"sqlite:///{(tmp_path / 'isolated.db').as_posix()}",
        "ATLAS_BASE_URL": base,
    })
    with (tmp_path / "server.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "atlas.api:app", "--host", "127.0.0.1",
             "--port", str(port)], cwd=root, env=environment, stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with ExitStack() as stack:
                public = stack.enter_context(httpx.Client(base_url=base, timeout=1))
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        pytest.fail(f"Owned server exited; inspect {tmp_path / 'server.log'}")
                    try:
                        ready = public.get("/readyz")
                        if ready.status_code == 200:
                            require_status(ready, 200)
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        pytest.fail(f"Owned server not ready; inspect {tmp_path / 'server.log'}")
                accounts = {}
                for role in ("admin", "member", "outsider"):
                    client = stack.enter_context(httpx.Client(base_url=base, timeout=10))
                    # Unicode strip/casefold, not lowercase-only or email conversion.
                    name = f"Straße-{role}"
                    credentials = {"username": f"\u2003{name}\u2003", "password": PASSWORD}
                    profile = require_status(mutate(client, "/auth/register", credentials), 201)
                    assert profile["username"] == name
                    assert "@" not in profile["username"]
                    assert PASSWORD not in str(profile)
                    if role == "member":
                        require_error(mutate(client, "/auth/register", {
                            "username": name.casefold(), "password": PASSWORD,
                        }), 409, "CONFLICT")
                    logged_in = require_status(mutate(client, "/auth/login", {
                        "username": f" {name.upper()} ", "password": PASSWORD,
                    }), 200)
                    assert logged_in["id"] == profile["id"]
                    assert require_status(client.get("/auth/me"), 200)["id"] == profile["id"]
                    accounts[role] = (client, profile)
                yield accounts
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_username_membership_preserves_identity_permissions_and_lifecycle(username_accounts):
    admin, _ = username_accounts["admin"]
    member, profile = username_accounts["member"]
    outsider, outsider_profile = username_accounts["outsider"]
    group = create_group(admin, "username-lifecycle")
    group_path = f"/v1/pool-groups/{group['id']}"
    path = group_path + "/members"
    body = {"username": f"\u2003{profile['username'].upper()}\u2003"}
    require_error(mutate(outsider, path, body), 404, "NOT_FOUND")
    headers = {"Idempotency-Key": "same-username-membership"}
    first = require_status(admin.post(path, json=body, headers=headers), 201)
    replay = require_status(admin.post(path, json=body, headers=headers), 201)
    assert replay == first
    assert first["user_id"] == profile["id"]
    assert first["username"] == profile["username"]
    assert first["role"] == "member"
    require_error(mutate(admin, path, {"username": profile["username"]}), 409, "CONFLICT")
    items = require_status(admin.get(path), 200)["items"]
    matching = [item for item in items if item["user_id"] == profile["id"]]
    assert len(matching) == 1
    assert matching[0]["username"] == profile["username"]
    for item in items:
        assert not {"password", "password_hash", "normalized_username", "token_hash"} & item.keys()
    require_status(member.get(group_path), 200)
    member_items = require_status(member.get(path), 200)["items"]
    assert any(item["user_id"] == profile["id"]
               and item["username"] == profile["username"] for item in member_items)
    require_error(mutate(member, path, {"username": outsider_profile["username"]}), 403, "FORBIDDEN")
    pool = create_pool(admin, group["id"])
    pool_path = group_path + f"/pools/{pool['id']}"
    require_error(mutate(member, pool_path + "/open"), 403, "FORBIDDEN")
    require_status(mutate(admin, pool_path + "/open"), 200)
    require_error(member.get(pool_path + "/results"), 409, "POOL_NOT_CLOSED")
    answer = {"option_id": "a"}
    require_status(mutate(member, pool_path + "/answers", answer), 201)
    require_error(mutate(member, pool_path + "/answers", answer), 409, "POOL_ALREADY_ANSWERED")
    require_error(mutate(member, pool_path + "/close"), 403, "FORBIDDEN")
    require_status(mutate(admin, pool_path + "/close"), 200)
    results = require_status(member.get(pool_path + "/results"), 200)
    assert results["total_answers"] == 1
    assert {item["option_id"]: item["count"] for item in results["options"]} == {"a": 1, "b": 0}
    assert {item["option_id"]: item["percentage"] for item in results["options"]} == {"a": 100, "b": 0}
    for item in [results, *results["options"]]:
        assert not {"username", "email", "user_id", "respondents", "answers"} & item.keys()
    require_status(mutate(admin, path + f"/{profile['id']}", method="DELETE"), 204)
    require_error(member.get(group_path), 404, "NOT_FOUND")
    require_error(member.get(pool_path + "/results"), 404, "NOT_FOUND")


@pytest.mark.parametrize("payload", [
    {}, {"username": "x", "email": "x@example.test"},
    {"username": ""}, {"username": "\u2003 "}, {"username": None},
    {"username": 123}, {"username": "x" * 201},
    {"username": "x", "unknown": True}, {"display_name": "x"},
    {"username": "x", "email": None}, {"username": [], "email": "x@example.test"},
    {"email": ""}, {"email": None}, {"email": "x@example.test", "unknown": True},
])
def test_member_selector_validation_is_atomic(username_accounts, payload):
    admin, _ = username_accounts["admin"]
    group = create_group(admin, "selector-validation")
    path = f"/v1/pool-groups/{group['id']}/members"
    before = require_status(admin.get(path), 200)
    require_error(mutate(admin, path, payload), 422, "VALIDATION_ERROR")
    assert require_status(admin.get(path), 200) == before


def test_unknown_username_is_safe_and_creates_no_membership(username_accounts):
    admin, _ = username_accounts["admin"]
    group = create_group(admin, "unknown-selector")
    path = f"/v1/pool-groups/{group['id']}/members"
    before = require_status(admin.get(path), 200)
    response = mutate(admin, path, {"username": "not-registered"})
    error = require_error(response, 404, "NOT_FOUND")
    assert error["message"] == "Resource not found"
    assert "not-registered" not in response.text
    assert require_status(admin.get(path), 200) == before
