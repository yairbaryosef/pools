"""Black-box checks for the supported SQLite persistence target.

These tests deliberately use only the HTTP boundary.  In particular, they do
not import a repository, inspect SQLite tables, or replace the database with an
in-memory fake.  The target supplied to CI must therefore be backed by the
same disposable SQLite file used by the application process.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import httpx
import pytest


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.fail(f"Environment blocker: set {name} for SQLite integration tests")
    return value


@pytest.fixture
def sqlite_database_url() -> str:
    """Require an explicit disposable SQLite URL; never silently use a default."""
    value = _required("ATLAS_DATABASE_URL")
    assert value.startswith("sqlite:///"), (
        "SQLite is the selected migration target; ATLAS_DATABASE_URL must use sqlite:///"
    )
    return value


@pytest.fixture
def sql_client() -> Iterator[httpx.Client]:
    base_url = _required("ATLAS_BASE_URL").rstrip("/")
    with httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=False) as client:
        yield client


@pytest.mark.database
def test_sqlite_schema_is_initialized_before_readiness(sqlite_database_url: str, sql_client: httpx.Client) -> None:
    """A ready application has opened and initialized its real SQL database."""
    response = sql_client.get("/readyz")
    assert response.status_code == 200, response.text
    assert response.headers.get("x-request-id")
    assert response.json() == {"status": "ready"}


@pytest.mark.database
def test_health_and_readiness_are_distinct_public_database_gates(sql_client: httpx.Client) -> None:
    health = sql_client.get("/healthz")
    ready = sql_client.get("/readyz")
    assert health.status_code == 200, health.text
    assert ready.status_code == 200, ready.text
    assert health.headers.get("x-request-id")
    assert ready.headers.get("x-request-id")


@pytest.mark.database
def test_database_target_is_not_configured_from_legacy_mongo_environment(
    sqlite_database_url: str,
) -> None:
    """The migration must not accidentally pass because a Mongo URI is present."""
    assert sqlite_database_url.startswith("sqlite:///")
    assert not os.getenv("ATLAS_MONGO_URI"), "legacy Mongo configuration must not drive SQL tests"
    assert not os.getenv("ATLAS_MONGO_DATABASE"), "legacy Mongo configuration must not drive SQL tests"


@pytest.mark.database
def test_real_sql_persistence_is_visible_to_a_second_public_client(
    sqlite_database_url: str, sql_client: httpx.Client
) -> None:
    """A second client sees the committed resource; this rejects process-memory stores."""
    session = _required("ATLAS_TEST_SESSION")
    cookie_name = _required("ATLAS_SESSION_COOKIE_NAME")
    sql_client.cookies.set(cookie_name, session)
    name = f"sql-persistence-{uuid.uuid4()}"
    created = sql_client.post(
        "/v1/pool-groups", json={"name": name}, headers={"Idempotency-Key": name}
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    with httpx.Client(base_url=str(sql_client.base_url), timeout=10.0) as second:
        second.cookies.set(cookie_name, session)
        listed = second.get("/v1/pool-groups")
    assert listed.status_code == 200, listed.text
    assert any(group["id"] == group_id for group in listed.json().get("items", []))
