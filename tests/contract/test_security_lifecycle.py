"""Authorization, answer privacy, persistence-boundary, and aggregate contracts."""

from __future__ import annotations

import pytest

from .conftest import create_group, create_pool, require_error, require_status


pytestmark = [pytest.mark.contract, pytest.mark.security, pytest.mark.database]


def _setup(as_user, users):
    admin = as_user("admin")
    member = as_user("member")
    group = create_group(admin, "contract-security-group")
    require_status(admin.post(f"/v1/pool-groups/{group['id']}/members",
                              json={"username": users["member"]["username"]},
                              headers={"Idempotency-Key": f"member-{group['id']}"}), 201)
    pool = create_pool(admin, group["id"])
    return admin, member, group["id"], pool["id"]


def test_nonmember_cannot_discover_group_or_pool(as_user, users):
    admin, member, group_id, pool_id = _setup(as_user, users)
    try:
        outsider = as_user("outsider")
        require_error(outsider.get(f"/v1/pool-groups/{group_id}"), 404, "NOT_FOUND")
        require_error(outsider.get(f"/v1/pool-groups/{group_id}/pools/{pool_id}"), 404, "NOT_FOUND")
    finally:
        admin.close()
        member.close()


def test_only_admin_can_open_and_members_only_answer(as_user, users):
    admin, member, group_id, pool_id = _setup(as_user, users)
    try:
        path = f"/v1/pool-groups/{group_id}/pools/{pool_id}"
        require_error(member.post(path + "/open", headers={"Idempotency-Key": "member-open"}), 403, "FORBIDDEN")
        require_status(admin.post(path + "/open", headers={"Idempotency-Key": "admin-open"}), 200)
        answer = require_status(member.post(path + "/answers", json={"option_id": "a"},
                                             headers={"Idempotency-Key": "answer-a"}), 201)
        assert "answer" not in answer and "user_id" not in answer
        require_error(member.post(path + "/answers", json={"option_id": "b"},
                                  headers={"Idempotency-Key": "answer-b"}), 409, "POOL_ALREADY_ANSWERED")
    finally:
        admin.close()
        member.close()


def test_results_are_hidden_until_close_and_have_no_identity(as_user, users):
    admin, member, group_id, pool_id = _setup(as_user, users)
    try:
        path = f"/v1/pool-groups/{group_id}/pools/{pool_id}"
        require_status(admin.post(path + "/open", headers={"Idempotency-Key": "admin-open"}), 200)
        require_error(member.get(path + "/results"), 409, "POOL_NOT_CLOSED")
        require_status(member.post(path + "/answers", json={"option_id": "a"},
                                   headers={"Idempotency-Key": "answer-a"}), 201)
        closed = require_status(admin.post(path + "/close", headers={"Idempotency-Key": "admin-close"}), 200)
        results = require_status(member.get(path + "/results"), 200)
        assert results["pool_id"] == pool_id
        assert results["total_answers"] == 1
        assert all("user_id" not in option and "respondent" not in option for option in results["options"])
        assert "results" in closed or closed["status"] == "closed"
    finally:
        admin.close()
        member.close()


def test_group_pool_list_and_detail_redact_answers_and_audit(as_user, users):
    admin, member, group_id, pool_id = _setup(as_user, users)
    try:
        pool_path = f"/v1/pool-groups/{group_id}/pools/{pool_id}"
        require_status(admin.post(pool_path + "/open", headers={"Idempotency-Key": "redact-open"}), 200)
        require_status(member.post(pool_path + "/answers", json={"option_id": "a"},
                                   headers={"Idempotency-Key": "redact-answer"}), 201)

        group = require_status(member.get(f"/v1/pool-groups/{group_id}"), 200)
        pools = require_status(member.get(f"/v1/pool-groups/{group_id}/pools"), 200)
        detail = require_status(member.get(pool_path), 200)
        for payload in (group, *pools.get("items", []), detail):
            assert "answers" not in payload
            assert "audit_events" not in payload
            assert "audit" not in payload
            assert "respondent" not in payload
            assert "user_id" not in payload or payload.get("user_id") == member.get("/auth/me").json().get("id")
    finally:
        admin.close()
        member.close()


def test_mutation_requires_idempotency_key(as_user):
    with as_user("admin") as client:
        response = client.post("/v1/pool-groups", json={"name": "missing-key"})
        require_error(response, 422, "VALIDATION_ERROR")


def test_removed_member_loses_future_access(as_user, users):
    admin, member, group_id, pool_id = _setup(as_user, users)
    try:
        me = require_status(member.get("/auth/me"), 200)
        require_status(admin.delete(f"/v1/pool-groups/{group_id}/members/{me['id']}",
                                    headers={"Idempotency-Key": "remove-member"}), 204)
        require_error(member.get(f"/v1/pool-groups/{group_id}"), 404, "NOT_FOUND")
        require_error(member.get(f"/v1/pool-groups/{group_id}/pools/{pool_id}"), 404, "NOT_FOUND")
    finally:
        admin.close()
        member.close()


def test_cursor_pagination_rejects_invalid_cursor_and_caps_limit(as_user):
    with as_user("admin") as client:
        group = create_group(client, "contract-pagination")
        response = client.get(f"/v1/pool-groups/{group['id']}/members", params={"limit": 101})
        require_error(response, 422, "VALIDATION_ERROR")
        response = client.get(f"/v1/pool-groups/{group['id']}/members", params={"cursor": "not-opaque"})
        require_error(response, 422, "VALIDATION_ERROR")
