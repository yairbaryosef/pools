from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import atlas.api as api_module
import atlas.database.sqlite as sqlite_module
import atlas.database.repositories as repositories_module
from atlas.api import create_app, create_production_app


class _Abuse:
    def check(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        return True

    def record(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        return True


class _Repositories:
    def __init__(self, db: object) -> None:
        self.db = db
        self.abuse_control = _Abuse()


class _Database:
    def __init__(self, settings: object) -> None:
        self.db = object()
        self.settings = settings
        self.indexes_ensured = False

    def ensure_indexes(self) -> None:
        self.indexes_ensured = True


def check(condition: bool, message: str = "") -> None:
    if not condition:
        raise AssertionError(message)


def test_production_composition_uses_sqlite_and_shared_abuse_control(monkeypatch) -> None:
    settings = object()
    monkeypatch.setattr(sqlite_module.SQLiteSettings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(sqlite_module, "SQLiteDatabase", _Database)
    monkeypatch.setattr(repositories_module, "SQLRepositories", _Repositories)
    captured: dict[str, object] = {}

    def composed(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(api_module, "create_app", composed)

    app = create_production_app()

    database = captured["database"]
    repositories = captured["repositories"]
    check(app is not None)
    check(isinstance(database, _Database))
    check(isinstance(repositories, _Repositories))
    check(captured["abuse_control"] is repositories.abuse_control)


def test_production_composition_bootstraps_configured_database(monkeypatch) -> None:
    """The production boundary must initialize indexes before serving requests."""
    settings = object()
    created: dict[str, object] = {}

    class _ConfiguredDatabase(_Database):
        def __init__(self, received_settings: object) -> None:
            super().__init__(received_settings)
            created["settings"] = received_settings

        def ensure_indexes(self) -> None:
            super().ensure_indexes()
            created["initialized"] = True

    monkeypatch.setattr(sqlite_module.SQLiteSettings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(sqlite_module, "SQLiteDatabase", _ConfiguredDatabase)
    monkeypatch.setattr(repositories_module, "SQLRepositories", _Repositories)
    monkeypatch.setattr(api_module, "create_app", lambda **kwargs: kwargs)

    composed = create_production_app()

    database = composed["database"]
    assert created == {"settings": settings, "initialized": True}
    assert isinstance(database, _ConfiguredDatabase)
    assert database.settings is settings
    assert composed["repositories"].db is database.db


def test_missing_sql_configuration_fails_before_production_composition(monkeypatch) -> None:
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="ATLAS_DATABASE_URL is required"):
        sqlite_module.SQLiteSettings.from_env()


def test_security_headers_are_present_at_served_response_boundary(monkeypatch) -> None:
    monkeypatch.delenv("ATLAS_ENABLE_HSTS", raising=False)
    app = create_app(repositories=object(), abuse_control=_Abuse())

    with TestClient(app) as client:
        response = client.get("/healthz")

    check(response.status_code == 200)
    check(
        response.headers["content-security-policy"]
        == (
            "default-src 'none'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'"
        )
    )
    check(response.headers["x-content-type-options"] == "nosniff")
    check(response.headers["referrer-policy"] == "no-referrer")
    check(
        response.headers["permissions-policy"]
        == "camera=(), microphone=(), geolocation=()"
    )
    check("strict-transport-security" not in response.headers)


def test_hsts_requires_https_and_explicit_deployment_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ENABLE_HSTS", "true")
    app = create_app(repositories=object(), abuse_control=_Abuse())

    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/healthz")

    check(
        response.headers["strict-transport-security"]
        == "max-age=31536000; includeSubDomains"
    )
