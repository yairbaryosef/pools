"""Focused checks for local SQLite composition and explicit URL precedence."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api import create_production_app
from atlas.database.sqlite import SQLiteSettings


def test_default_local_settings_are_file_backed() -> None:
    settings = SQLiteSettings.default_local()

    assert settings.url.startswith("sqlite:///")
    assert settings.path != ":memory:"
    assert Path(settings.path).name == "atlas-dev.sqlite3"


def test_explicit_database_url_is_honored(monkeypatch, tmp_path: Path) -> None:
    configured = f"sqlite:///{tmp_path / 'explicit.sqlite3'}"
    monkeypatch.setenv("ATLAS_DATABASE_URL", configured)

    assert SQLiteSettings.from_env().url == configured


def test_missing_database_url_uses_repository_local_default(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    expected = f"sqlite:///{tmp_path / 'dev.sqlite3'}"
    monkeypatch.setattr(
        SQLiteSettings,
        "default_local",
        classmethod(lambda cls: cls(expected)),
    )

    assert SQLiteSettings.from_env().url == expected


def test_blank_defaults_but_non_sqlite_url_is_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        SQLiteSettings,
        "default_local",
        classmethod(lambda cls: cls(f"sqlite:///{tmp_path / 'blank.sqlite3'}")),
    )
    for configured in ("", "   "):
        monkeypatch.setenv("ATLAS_DATABASE_URL", configured)
        assert SQLiteSettings.from_env().path.endswith("blank.sqlite3")

    monkeypatch.setenv("ATLAS_DATABASE_URL", "postgresql:///atlas.sqlite3")
    try:
        SQLiteSettings.from_env()
    except RuntimeError as exc:
        assert str(exc) == "ATLAS_DATABASE_URL must be a sqlite URL"
    else:
        raise AssertionError("invalid explicit URL was accepted")


def test_health_and_readiness_work_without_local_database_environment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        SQLiteSettings,
        "default_local",
        classmethod(lambda cls: cls(f"sqlite:///{tmp_path / 'dev.sqlite3'}")),
    )

    app = create_production_app()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
