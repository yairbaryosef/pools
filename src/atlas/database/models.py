"""Typed persistence records.  These records deliberately contain no policy or HTTP types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

PoolStatus = Literal["draft", "open", "closed"]
MemberRole = Literal["admin", "member"]


@dataclass(frozen=True, slots=True)
class PoolOption:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class Answer:
    user_id: str
    option_id: str
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    group_id: str
    actor_user_id: str | None
    request_id: str
    action: str
    entity_type: Literal["group", "member", "pool", "answer"]
    entity_id: str
    metadata: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class Cursor:
    created_at: datetime
    pool_id: str
    group_id: str
    status: PoolStatus
