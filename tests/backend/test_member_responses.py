from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atlas.application.errors import ApplicationError
from atlas.application.services import PoolService


class _Repositories:
    def __init__(self) -> None:
        self.users = {
            "admin": {"_id": "admin", "email": "admin@example.test", "password_hash": "secret"},
            "member": {"_id": "member", "email": "member@example.test", "password_hash": "secret"},
        }
        self.group = {
            "_id": "group",
            "admin_user_id": "admin",
            "members": {
                "admin": {"role": "admin", "created_at": datetime.now(UTC), "removed_at": None},
            },
        }
        self.member_page = {"items": [], "next_cursor": "opaque"}

    def get_group(self, group_id: str) -> dict | None:
        return self.group if group_id == "group" else None

    def find_user_by_email(self, email: str) -> dict | None:
        return next((user for user in self.users.values() if user["email"] == email), None)

    def get_user(self, user_id: str) -> dict | None:
        return self.users.get(user_id)

    def add_member(self, group_id: str, user_id: str, *, event: object) -> bool:
        self.group["members"][user_id] = {
            "role": "member", "created_at": event.occurred_at, "removed_at": None,
        }
        return True

    def list_members(self, group_id: str, limit: int, cursor: str | None) -> dict:
        return self.member_page


def test_add_and_list_member_responses_include_only_safe_email() -> None:
    repos = _Repositories()
    service = PoolService(repos)

    added = service.add_member("group", "admin", "member@example.test", "request-1")
    assert added["email"] == "member@example.test"
    assert "password_hash" not in added

    repos.member_page = {
        "items": [{
            "group_id": "group", "user_id": "member", "role": "member",
            "created_at": added["created_at"],
        }],
        "next_cursor": "opaque",
    }
    listed = service.get_members("group", "admin", 25, None)
    assert listed["items"] == [{
        "group_id": "group", "user_id": "member", "email": "member@example.test",
        "role": "member", "created_at": added["created_at"],
    }]
    assert listed["next_cursor"] == "opaque"
    assert all("password_hash" not in item for item in listed["items"])


@pytest.mark.parametrize("actor", ["outsider", "removed"])
def test_member_listing_preserves_group_privacy_for_outsider_and_removed_member(actor: str) -> None:
    repos = _Repositories()
    if actor == "removed":
        repos.group["members"][actor] = {"role": "member", "removed_at": datetime.now(UTC)}
    with pytest.raises(ApplicationError) as error:
        PoolService(repos).get_members("group", actor, 25, None)
    assert error.value.code == "NOT_FOUND"
