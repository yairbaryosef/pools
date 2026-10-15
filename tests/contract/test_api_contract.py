"""REST contract tests derived from docs/API.md and docs/PRD.md."""

from __future__ import annotations

import os
import uuid

import pytest

from .conftest import create_group, create_pool, require_error, require_status


pytestmark = pytest.mark.contract


def test_liveness_and_readiness_are_public(public_client):
    assert public_client.get("/healthz").status_code == 200
    assert public_client.get("/readyz").status_code in {200, 503}


def test_registration_creates_account_without_echoing_password(public_client):
    username = os.getenv("ATLAS_TEST_REGISTRATION_USERNAME")
    password = os.getenv("ATLAS_TEST_REGISTRATION_PASSWORD")
    if not username or not password:
        pytest.fail(
            "Environment blocker: set ATLAS_TEST_REGISTRATION_USERNAME and "
            "ATLAS_TEST_REGISTRATION_PASSWORD"
        )
    response = public_client.post(
        "/auth/register", json={"username": username, "password": password},
        headers={"Idempotency-Key": f"register-{username}"}
    )
    body = require_status(response, 201)
    assert body.get("username") == username
    assert "password" not in body


def test_login_rejects_invalid_password_without_secret_leak(public_client, users):
    account = users["admin"]
    response = public_client.post(
        "/auth/login", json={"username": account["username"], "password": "wrong-password"},
        headers={"Idempotency-Key": f"bad-login-{account['username']}"}
    )
    require_error(response, 401, "AUTHENTICATION_FAILED")
    assert account["password"] not in response.text


def test_missing_session_is_safe(public_client):
    response = public_client.get("/auth/me")
    require_error(response, 401, "AUTHENTICATION_REQUIRED")


def test_group_creation_and_member_listing_uses_username_only(as_user, users):
    """Membership is selected by the registered username, never by email."""
    with as_user("admin") as client, as_user("member") as member:
        profile = require_status(member.get("/auth/me"), 200)
        assert profile["username"] == users["member"]["username"]
        group = create_group(client, "contract-group-members")
        group_id = group["id"]
        added = require_status(
            client.post(f"/v1/pool-groups/{group_id}/members",
                        json={"username": f"  {profile['username'].upper()}  "},
                        headers={"Idempotency-Key": f"member-{group_id}"}), 201
        )
        assert added["user_id"] == profile["id"]
        assert added["username"] == profile["username"]
        assert "email" not in added
        body = require_status(client.get(f"/v1/pool-groups/{group_id}/members"), 200)
        matching = [item for item in body["items"] if item["user_id"] == profile["id"]]
        assert len(matching) == 1
        assert matching[0]["username"] == profile["username"]
        assert "email" not in matching[0]
        require_status(member.get(f"/v1/pool-groups/{group_id}"), 200)
        require_error(client.post(
            f"/v1/pool-groups/{group_id}/members", json={"username": profile["username"]},
            headers={"Idempotency-Key": f"duplicate-email-{group_id}"},
        ), 409, "CONFLICT")


def test_email_is_not_a_membership_selector(as_user, users):
    with as_user("admin") as client:
        group = create_group(client, "username-selector-only")
        path = f"/v1/pool-groups/{group['id']}/members"
        for payload in ({"email": "member@example.test"},
                        {"username": users["member"]["username"], "email": "member@example.test"}):
            require_error(client.post(path, json=payload,
                                       headers={"Idempotency-Key": f"no-email-{len(payload)}"}),
                          422, "VALIDATION_ERROR")


def test_unknown_fields_and_malformed_ids_are_rejected(as_user):
    with as_user("admin") as client:
        response = client.post("/v1/pool-groups", json={"name": "x", "unknown": True},
                               headers={"Idempotency-Key": "unknown-field"})
        require_error(response, 422, "VALIDATION_ERROR")
        response = client.get(f"/v1/pool-groups/{uuid.uuid4().hex}")
        require_error(response, 422, "VALIDATION_ERROR")


def test_pool_validation_requires_two_distinct_bounded_options(as_user):
    with as_user("admin") as client:
        group = create_group(client, "contract-group-validation")
        path = f"/v1/pool-groups/{group['id']}/pools"
        for payload in (
            {"question": " ", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
            {"question": "Q", "options": [{"id": "a", "label": "A"}]},
            {"question": "Q", "options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]},
        ):
            require_error(client.post(path, json=payload,
                                       headers={"Idempotency-Key": f"invalid-{len(payload['options'])}-{payload['question']}"}),
                          422, "VALIDATION_ERROR")


def test_pool_lifecycle_and_draft_edit_lock(as_user):
    with as_user("admin") as client:
        group = create_group(client, "contract-group-lifecycle")
        pool = create_pool(client, group["id"])
        pool_path = f"/v1/pool-groups/{group['id']}/pools/{pool['id']}"
        assert require_status(client.get(pool_path), 200)["status"] == "draft"
        opened = require_status(client.post(pool_path + "/open", headers={"Idempotency-Key": "open-1"}), 200)
        assert opened["status"] == "open"
        require_error(client.patch(pool_path, json={"question": "changed"},
                                   headers={"Idempotency-Key": "edit-1"}), 409, "INVALID_POOL_TRANSITION")
        closed = require_status(client.post(pool_path + "/close", headers={"Idempotency-Key": "close-1"}), 200)
        assert closed["status"] == "closed"
        require_error(client.post(pool_path + "/open", headers={"Idempotency-Key": "open-2"}), 409, "INVALID_POOL_TRANSITION")


def test_idempotent_mutation_replays_same_result(as_user):
    with as_user("admin") as client:
        key = "idempotent-group-contract"
        first = client.post("/v1/pool-groups", json={"name": key}, headers={"Idempotency-Key": key})
        second = client.post("/v1/pool-groups", json={"name": key}, headers={"Idempotency-Key": key})
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
