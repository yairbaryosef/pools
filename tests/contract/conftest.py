"""Public-boundary fixtures for Atlas contract tests.

The suite deliberately talks to an approved HTTP target only.  It does not import
the ASGI application or inspect MongoDB.  A real run must provide the target and
username/password test accounts through environment variables.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest


@pytest.fixture
def api_base_url() -> str:
    value = os.getenv("ATLAS_BASE_URL")
    if not value:
        pytest.fail("Environment blocker: set ATLAS_BASE_URL to an approved running API target")
    return value.rstrip("/")


@pytest.fixture
def public_client(api_base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api_base_url, timeout=10.0, follow_redirects=False) as client:
        yield client


@pytest.fixture
def users() -> dict[str, dict[str, str]]:
    raw = os.getenv("ATLAS_TEST_USERS")
    if not raw:
        pytest.fail("Environment blocker: set ATLAS_TEST_USERS JSON for admin/member/outsider")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Invalid ATLAS_TEST_USERS JSON: {exc}")
    if not isinstance(value, dict) or not {"admin", "member", "outsider"} <= value.keys():
        pytest.fail("ATLAS_TEST_USERS must contain admin, member, and outsider")
    result: dict[str, dict[str, str]] = {}
    for role, account in value.items():
        if not isinstance(account, dict) or not {"username", "password"} <= account.keys():
            pytest.fail(f"ATLAS_TEST_USERS[{role}] must contain username and password")
        result[str(role)] = {"username": str(account["username"]), "password": str(account["password"])}
    return result


@pytest.fixture
def session_cookie_name() -> str:
    value = os.getenv("ATLAS_SESSION_COOKIE_NAME")
    if not value:
        pytest.fail("Environment blocker: set ATLAS_SESSION_COOKIE_NAME for the application session cookie")
    return value


@pytest.fixture
def as_user(
    public_client: httpx.Client, users: dict[str, dict[str, str]], session_cookie_name: str
) -> Callable[[str], httpx.Client]:
    def make(role: str) -> httpx.Client:
        if role not in users:
            pytest.fail(f"Missing configured session role: {role}")
        client = httpx.Client(
            base_url=str(public_client.base_url),
            timeout=public_client.timeout,
            follow_redirects=False,
        )
        response = client.post("/auth/login", json=users[role], headers={"Idempotency-Key": f"login-{role}"})
        require_status(response, 200)
        if not client.cookies.get(session_cookie_name):
            pytest.fail("Username/password login did not establish the configured session cookie")
        return client

    return make


@pytest.fixture
def member_email() -> str:
    value = os.getenv("ATLAS_TEST_MEMBER_EMAIL")
    if not value:
        pytest.fail("Environment blocker: set ATLAS_TEST_MEMBER_EMAIL for the pre-existing test member")
    return value


def require_status(response: httpx.Response, expected: int) -> dict[str, Any]:
    assert response.status_code == expected, response.text
    assert response.headers.get("x-request-id"), "Every response must carry X-Request-ID (API.md §1)"
    if not response.content:
        return {}
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def require_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    payload = require_status(response, status)
    error = payload.get("error")
    assert isinstance(error, dict)
    assert error.get("code") == code
    assert error.get("request_id") == response.headers["x-request-id"]
    return error


def create_group(client: httpx.Client, name: str) -> dict[str, Any]:
    return require_status(
        client.post("/v1/pool-groups", json={"name": name}, headers={"Idempotency-Key": name}), 201
    )


def create_pool(client: httpx.Client, group_id: str) -> dict[str, Any]:
    return require_status(
        client.post(
            f"/v1/pool-groups/{group_id}/pools",
            json={"question": "Which option?", "options": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}]},
            headers={"Idempotency-Key": f"pool-{group_id}"},
        ),
        201,
    )
