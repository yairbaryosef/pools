from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atlas.application.errors import ApplicationError
from atlas.application.services import PoolService
from atlas.database.models import AuditEvent
from atlas.database.repositories import SQLRepositories
from atlas.database.sqlite import SQLiteDatabase, SQLiteSettings


class _Transaction:
    def run_transaction(self, callback):
        return callback(object())


class _Repositories:
    def __init__(self, status: str = "draft") -> None:
        self.pool = {
            "question": "Q",
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "status": status,
            "opened_at": None,
            "closed_at": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "answers": {},
        }
        self.session_seen = False
        self.audit_count = 0

    def get_group(self, group_id: str):
        return {"admin_user_id": "admin", "members": {"admin": {"removed_at": None}}}

    def get_pool(self, group_id: str, pool_id: str, *, session=None):
        self.session_seen = self.session_seen or session is not None
        return {"pools": {pool_id: self.pool}}

    def transition_pool(self, group_id, pool_id, expected, target, actor, event, *, session):
        self.session_seen = session is not None
        if self.pool["status"] != expected:
            return False
        self.pool["status"] = target
        self.audit_count += 1
        return True


def test_draft_open_returns_updated_pool_from_transaction() -> None:
    repos = _Repositories()
    result = PoolService(repos, _Transaction()).transition(
        "group", "pool", "admin", "open", "request"
    )

    assert result["status"] == "open"
    assert repos.pool["status"] == "open"
    assert repos.session_seen
    assert repos.audit_count == 1


@pytest.mark.parametrize("status", ["open", "closed"])
def test_invalid_open_transition_preserves_state_and_has_no_audit(status: str) -> None:
    repos = _Repositories(status)

    with pytest.raises(ApplicationError) as raised:
        PoolService(repos, _Transaction()).transition(
            "group", "pool", "admin", "open", "request"
        )

    assert raised.value.code == "INVALID_POOL_TRANSITION"
    assert raised.value.status == 409
    assert repos.pool["status"] == status
    assert repos.audit_count == 0


def test_transition_returns_state_after_atomic_embedded_audit_write() -> None:
    """Regression: the response must come from the same transaction as the write."""
    repos = _Repositories()
    service = PoolService(repos, _Transaction())

    opened = service.transition("group", "pool", "admin", "open", "live-open")

    assert opened["status"] == "open"
    assert repos.session_seen is True
    assert repos.audit_count == 1


def test_sql_transition_uses_one_atomic_transaction_for_state_and_audit() -> None:
    database = SQLiteDatabase(SQLiteSettings("sqlite:///:memory:"))
    database.ensure_indexes()
    database.db.execute(
        "INSERT INTO users(id, username, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("admin", "admin", "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
    )
    database.db.execute(
        "INSERT INTO pool_groups(id, name, admin_user_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("group", "Group", "admin", "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
    )
    database.db.execute(
        "INSERT INTO pools(id, group_id, question, status, options_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("pool", "group", "Q", "draft", '[{"id":"a","label":"A"}, {"id":"b","label":"B"}]',
         "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
    )
    repositories = SQLRepositories(database.db)
    event = AuditEvent(
        "group", "admin", "request", "pool_open", "pool", "pool", {}, datetime.now(UTC)
    )

    assert database.run_transaction(lambda session: repositories.transition_pool(
        "group", "pool", "draft", "open", "admin", event, session=session
    ))
    assert database.db.execute("SELECT status FROM pools WHERE id='pool'").fetchone()[0] == "open"
    assert (
        database.db.execute("SELECT action FROM audit_events WHERE entity_id='pool'").fetchone()[0]
        == "pool_open"
    )
