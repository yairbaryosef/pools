"""Focused checks for the documented local development launcher."""

from __future__ import annotations

import builtins
import os
from pathlib import Path

import pytest
from scripts.dev import _ensure_local_database_url, _load_local_environment


def test_explicit_environment_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ATLAS_DATABASE_URL=sqlite:///from-file.sqlite3\n", encoding="utf-8"
    )
    configured = "sqlite:///from-shell.sqlite3"
    monkeypatch.setenv("ATLAS_DATABASE_URL", configured)

    _load_local_environment(env_file)

    if os.environ["ATLAS_DATABASE_URL"] != configured:
        raise AssertionError("explicit ATLAS_DATABASE_URL was overwritten")


def test_missing_env_file_does_not_require_python_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_import = builtins.__import__

    def reject_dotenv(name: str, *args: object, **kwargs: object) -> object:
        if name == "dotenv":
            raise ModuleNotFoundError("dotenv")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_dotenv)

    _load_local_environment(tmp_path / ".env")


def test_present_env_file_without_parser_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ATLAS_DATABASE_URL=sqlite:///from-file.sqlite3\n", encoding="utf-8")

    real_import = builtins.__import__

    def reject_dotenv(name: str, *args: object, **kwargs: object) -> object:
        if name == "dotenv":
            raise ModuleNotFoundError("dotenv")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_dotenv)

    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    _load_local_environment(env_file)
    if "ATLAS_DATABASE_URL" in os.environ:
        raise AssertionError("malformed local environment changed the process environment")


def test_malformed_env_file_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"ATLAS_DATABASE_URL=\xff\xfe\n")
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)

    _load_local_environment(env_file)

    if "ATLAS_DATABASE_URL" in os.environ:
        raise AssertionError("malformed local environment changed the process environment")


def test_launcher_exports_default_before_app_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The clean ``npm run dev`` path gives Uvicorn a URL before import."""
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)

    _ensure_local_database_url(tmp_path)

    assert os.environ["ATLAS_DATABASE_URL"] == (
        f"sqlite:///{tmp_path / 'database' / 'atlas-dev.sqlite3'}"
    )
