"""SQLite connection lifecycle, URL parsing, schema and transaction boundary."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class SQLiteSettings:
    url: str

    @classmethod
    def default_local(cls) -> SQLiteSettings:
        root = Path(__file__).resolve().parents[3]
        return cls(f"sqlite:///{root / 'database' / 'atlas-dev.sqlite3'}")

    @classmethod
    def from_env(cls) -> SQLiteSettings:
        # Local development is deliberately usable from a clean environment.
        # Treat an unset or blank variable as the local file default, but do
        # not turn a non-empty typo (or another database scheme) into a local
        # database silently.
        value = os.environ.get("ATLAS_DATABASE_URL")
        if value is None or not value.strip():
            return cls.default_local()
        if not value or not value.startswith("sqlite:///"):
            raise RuntimeError("ATLAS_DATABASE_URL must be a sqlite URL")
        return cls(value)

    @property
    def path(self) -> str:
        value = self.url[len("sqlite:///"):]
        if value == ":memory:":
            return ":memory:"
        return str(Path(value).expanduser())

class SQLiteDatabase:
    def __init__(self, settings: SQLiteSettings) -> None:
        self.settings = settings
        if settings.path != ":memory:":
            Path(settings.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            settings.path, check_same_thread=False, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")

    @property
    def db(self) -> sqlite3.Connection:
        return self.connection

    def ensure_indexes(self) -> None:
        self.connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def run_transaction(self, callback: Callable[[sqlite3.Connection], T]) -> T:
        with self.transaction() as connection:
            return callback(connection)

    def ping(self) -> bool:
        try:
            self.connection.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        self.connection.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, google_issuer TEXT, google_subject TEXT, email TEXT,
 normalized_email TEXT, username TEXT, normalized_username TEXT, password_hash TEXT,
 display_name TEXT, avatar_url TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google ON users(google_issuer,google_subject) WHERE google_issuer IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users(normalized_email) WHERE normalized_email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users(normalized_username) WHERE normalized_username IS NOT NULL;
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT, last_seen_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_sessions_active ON sessions(token_hash,expires_at);
CREATE TABLE IF NOT EXISTS pool_groups (id TEXT PRIMARY KEY, name TEXT NOT NULL, admin_user_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (group_id TEXT NOT NULL REFERENCES pool_groups(id), user_id TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL, created_at TEXT NOT NULL, removed_at TEXT, PRIMARY KEY(group_id,user_id));
CREATE INDEX IF NOT EXISTS ix_memberships_user ON memberships(user_id,removed_at);
CREATE TABLE IF NOT EXISTS pools (id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES pool_groups(id), question TEXT NOT NULL, status TEXT NOT NULL, options_json TEXT NOT NULL, opened_at TEXT, closed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pools_group_status ON pools(group_id,status,created_at,id);
CREATE TABLE IF NOT EXISTS answers (pool_id TEXT NOT NULL REFERENCES pools(id), user_id TEXT NOT NULL REFERENCES users(id), option_id TEXT NOT NULL, submitted_at TEXT NOT NULL, PRIMARY KEY(pool_id,user_id));
CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL, actor_user_id TEXT, request_id TEXT NOT NULL, action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, metadata_json TEXT NOT NULL, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency (scope_key TEXT PRIMARY KEY, principal TEXT NOT NULL, group_id TEXT, method TEXT NOT NULL, route TEXT NOT NULL, request_hash TEXT NOT NULL, response_json TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_idempotency_expiry ON idempotency(expires_at);
CREATE TABLE IF NOT EXISTS abuse_control (id TEXT PRIMARY KEY, bucket TEXT NOT NULL, key TEXT NOT NULL, count INTEGER NOT NULL, expires_at TEXT NOT NULL, UNIQUE(bucket,key));
CREATE INDEX IF NOT EXISTS ix_abuse_expiry ON abuse_control(expires_at);
"""
