"""Regression coverage for a clean local startup without database config."""

from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

import atlas.api as api_module
from atlas.database.sqlite import SQLiteSettings


def test_clean_startup_health_does_not_raise_old_missing_url_error(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        SQLiteSettings,
        "default_local",
        classmethod(lambda cls: cls(f"sqlite:///{tmp_path / 'clean-start.sqlite3'}")),
    )

    # Re-import the actual uvicorn ``atlas.api:app`` entrypoint, then exercise
    # its lazy composition path with no URL in the environment.
    app = importlib.reload(api_module).app
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
