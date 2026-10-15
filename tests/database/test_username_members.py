"""Repository contracts for API.md §3 using only disposable file-backed SQLite."""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from atlas.database.sqlite import SQLiteDatabase, SQLiteSettings
from atlas.database.sqlite_repositories import SQLRepositories


@pytest.fixture
def database(tmp_path: Path) -> Iterator[SQLiteDatabase]:
    db = SQLiteDatabase(SQLiteSettings(f"sqlite:///{tmp_path / 'members.sqlite3'}"))
    db.ensure_indexes()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.parametrize("selector", ["Straße", " STRASSE ", "strasse"])
def test_normalized_username_lookup(database: SQLiteDatabase, selector: str) -> None:
    repo = SQLRepositories(database.db)
    user_id = str(uuid4())
    repo.create_password_user(user_id, " Straße ", "test-only-hash")
    user = repo.find_user_by_username(selector)
    assert user is not None
    assert user["id"] == user_id
    assert user["username"] == "Straße"
    assert user["email"] is None
    assert repo.find_user_by_username("unknown") is None
    assert repo.find_user_by_username("' OR 1=1 --") is None


def test_username_unique_index_is_used(database: SQLiteDatabase) -> None:
    repo = SQLRepositories(database.db)
    repo.create_password_user(str(uuid4()), "Straße", "test-only-hash")
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_password_user(str(uuid4()), " STRASSE ", "test-only-hash")
    plan = database.db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM users WHERE normalized_username=?", ("strasse",)
    ).fetchall()
    assert any("uq_users_username" in row[3] and "SEARCH" in row[3] for row in plan)
    assert database.db.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_member_projection_is_group_scoped_and_bounded(database: SQLiteDatabase) -> None:
    repo = SQLRepositories(database.db)
    admin, member, outsider, email_user = [str(uuid4()) for _ in range(4)]
    for user_id, name in [(admin, "Admin"), (member, " Member "), (outsider, "Outsider")]:
        repo.create_password_user(user_id, name, "test-only-hash")
    # Seed an existing email-only account; Google provisioning is a separate capability.
    database.db.execute(
        "INSERT INTO users(id,email,normalized_email,created_at,updated_at) VALUES(?,?,?,?,?)",
        (email_user, "Original@example.test", "original@example.test",
         "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    group_id, other_group = str(uuid4()), str(uuid4())
    repo.create_group(group_id, "Selected group", admin)
    repo.create_group(other_group, "Other group", outsider)
    assert repo.add_member(group_id, member)
    assert repo.add_member(group_id, email_user)
    assert not repo.add_member(group_id, member)
    items = repo.list_members(group_id)["items"]
    assert {item["user_id"]: item["username"] for item in items} == {
        admin: "Admin", member: "Member", email_user: None,
    }
    for item in items:
        assert set(item) == {"group_id", "user_id", "role", "created_at", "username"}
        assert item["group_id"] == group_id
        assert isinstance(item["created_at"], datetime)
    assert len(repo.list_members(group_id, limit=1)["items"]) == 1
    assert repo.list_members(str(uuid4()))["items"] == []
    assert repo.remove_member(group_id, member)
    assert member not in {item["user_id"] for item in repo.list_members(group_id)["items"]}
    assert database.db.execute(
        "SELECT removed_at FROM memberships WHERE group_id=? AND user_id=?", (group_id, member)
    ).fetchone()[0] is not None
    found = repo.find_user_by_email("ORIGINAL@EXAMPLE.TEST")
    assert found is not None and found["id"] == email_user


def test_username_projection_survives_reopen_and_bootstrap(database: SQLiteDatabase) -> None:
    repo = SQLRepositories(database.db)
    user_id, group_id = str(uuid4()), str(uuid4())
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repo.create_password_user(user_id, " PreservedName ", "test-only-hash", now)
    repo.create_group(group_id, "Persisted", user_id, now)
    before = dict(database.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    second = SQLiteDatabase(database.settings)
    try:
        second.ensure_indexes()
        second.ensure_indexes()
        reread = SQLRepositories(second.db)
        found = reread.find_user_by_username(" preservedname ")
        assert found is not None and found["id"] == user_id
        assert reread.list_members(group_id)["items"] == [{
            "group_id": group_id, "user_id": user_id, "role": "admin",
            "created_at": now, "username": "PreservedName",
        }]
        assert dict(second.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()) == before
    finally:
        second.close()
