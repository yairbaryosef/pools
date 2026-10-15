from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from atlas.database.models import AuditEvent, PoolOption

from .errors import (
    ApplicationError,
    AuthenticationFailed,
    AuthenticationRequired,
    PersistenceContractError,
)

# The API uses this port for authentication abuse controls. Implementations
# must be backed by an atomic shared store; the application deliberately has
# no process-local fallback.
class AbuseControl(Protocol):
    def check(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool: ...
    def record(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool: ...


class Repositories(Protocol):
    def get_group(self, group_id: str) -> dict[str, Any] | None: ...
    def get_pool(
        self, group_id: str, pool_id: str, *, session: Any = None
    ) -> dict[str, Any] | None: ...

class Transactions(Protocol):
    def run_transaction(self, callback: Any) -> Any: ...

def utcnow() -> datetime:
    return datetime.now(UTC)


class PoolService:
    """Application policy layer over the typed persistence ports."""
    def __init__(self, repos: Repositories, database: Transactions | None = None) -> None:
        self.repos, self.database = repos, database

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        salt_encoded = base64.urlsafe_b64encode(salt).decode()
        digest_encoded = base64.urlsafe_b64encode(digest).decode()
        return f"scrypt$16384$8$1${salt_encoded}${digest_encoded}"

    @staticmethod
    def verify_password(password: str, encoded: str) -> bool:
        try:
            scheme, n, r, p, salt_s, digest_s = encoded.split("$", 5)
            # Password records are application-owned data.  Do not allow a
            # corrupt or tampered record to select an expensive work factor.
            if scheme != "scrypt" or (n, r, p) != ("16384", "8", "1"):
                return False
            salt = base64.b64decode(salt_s.encode(), altchars=b"-_", validate=True)
            expected = base64.b64decode(digest_s.encode(), altchars=b"-_", validate=True)
            if len(salt) != 16 or len(expected) != 64:
                return False
            actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, binascii.Error):
            return False

    @staticmethod
    def dummy_password_hash() -> str:
        """A valid, fixed-cost record used to equalize unknown-user logins."""
        salt = base64.urlsafe_b64encode(b"atlas-dummy-salt").decode()
        digest = base64.urlsafe_b64encode(b"atlas-dummy-digest".ljust(64, b"\0")).decode()
        return "scrypt$16384$8$1$" + salt + "$" + digest

    def _capability(self, name: str) -> Any:
        method = getattr(self.repos, name, None)
        if not callable(method):
            raise PersistenceContractError(name)
        return method

    def register(self, username: str, password: str) -> dict[str, Any]:
        now = utcnow()
        user_id = str(uuid4())
        record = self._capability("create_password_user")(
            user_id, username, self.hash_password(password), now
        )
        return self.public_user(record or {"id": user_id, "username": username, "created_at": now})

    def login(self, username: str, password: str) -> tuple[dict[str, Any], str]:
        record = self._capability("find_user_by_username")(username)
        # Always perform one bounded verification, including for an unknown
        # account.  Stored parameters are accepted only at the fixed work
        # factor enforced by verify_password().
        password_hash = (
            str(record.get("password_hash", "")) if record else self.dummy_password_hash()
        )
        if not self.verify_password(password, password_hash):
            raise AuthenticationFailed()
        token = secrets.token_urlsafe(32)
        self._capability("create_session")(
            str(uuid4()), str(record["_id"] if "_id" in record else record["id"]),
            hashlib.sha256(token.encode()).hexdigest(),
            utcnow().replace(microsecond=0) + timedelta(days=7),
        )
        return self.public_user(record), token

    def authenticate_session(self, token: str) -> dict[str, Any]:
        session = self._capability("get_active_session")(hashlib.sha256(token.encode()).hexdigest())
        if not session:
            raise AuthenticationRequired()
        return session

    def logout(self, token: str) -> None:
        session = self.authenticate_session(token)
        self._capability("revoke_session")(str(session["_id"]))

    @staticmethod
    def public_user(record: dict[str, Any]) -> dict[str, Any]:
        # Repositories may expose an internal identifier alias, while the API
        # contract always exposes the stable primitive identifier as ``id``.
        user_id = record.get("id") or record.get("_id")
        public: dict[str, Any] = {}
        if user_id is not None:
            public["id"] = str(user_id)
        for key in ("username", "email", "display_name", "avatar_url", "created_at"):
            if key in record:
                public[key] = record[key]
        return public

    def group_for_member(self, group_id: str, user_id: str) -> dict[str, Any]:
        group = self.repos.get_group(group_id)
        member = group and group.get("members", {}).get(user_id)
        if not group or not member or member.get("removed_at") is not None:
            raise ApplicationError("NOT_FOUND", "Resource not found", 404)
        # The persistence read model may contain membership details used for
        # authorization. They are not part of the group read contract.
        return self._public_group(group, group_id)

    @staticmethod
    def _public_group(group: dict[str, Any], group_id: str) -> dict[str, Any]:
        members = group.get("members", {})
        return {
            "id": group_id,
            "name": group.get("name"),
            "admin_user_id": group.get("admin_user_id"),
            "member_count": sum(1 for member in members.values()
                                 if member.get("removed_at") is None),
            "created_at": group.get("created_at"),
            "updated_at": group.get("updated_at"),
        }

    def admin_group(self, group_id: str, user_id: str) -> dict[str, Any]:
        group = self.group_for_member(group_id, user_id)
        if group.get("admin_user_id") != user_id:
            raise ApplicationError("FORBIDDEN", "Forbidden", 403)
        return group

    def pool(self, group_id: str, pool_id: str, user_id: str) -> dict[str, Any]:
        self.group_for_member(group_id, user_id)
        document = self.repos.get_pool(group_id, pool_id)
        if not document:
            raise ApplicationError("NOT_FOUND", "Resource not found", 404)
        return self._public_pool(document["pools"][pool_id], pool_id, group_id, user_id)

    @staticmethod
    def _public_pool(
        pool: dict[str, Any], pool_id: str, group_id: str, user_id: str
    ) -> dict[str, Any]:
        # Whitelist the documented read model.  In particular, do not copy
        # embedded answers or audit rows from the persistence document.
        result = {key: pool[key] for key in (
            "question", "options", "status", "opened_at", "closed_at",
            "created_at", "updated_at") if key in pool}
        result.update({"id": pool_id, "group_id": group_id,
                       "has_answered": user_id in pool.get("answers", {})})
        return result

    def list_pools(self, group_id: str, user_id: str) -> list[dict[str, Any]]:
        self.group_for_member(group_id, user_id)
        pools = self._capability("list_pools")(group_id)
        return [self._public_pool(pool, str(pool["id"]), group_id, user_id) for pool in pools]

    def transition(
        self, group_id: str, pool_id: str, user_id: str, target: str, request_id: str
    ) -> dict[str, Any]:
        self.admin_group(group_id, user_id)
        pool = self.pool(group_id, pool_id, user_id)
        expected = "draft" if target == "open" else "open"
        if pool.get("status") != expected:
            raise ApplicationError("INVALID_POOL_TRANSITION", "Invalid pool transition", 409)
        event = AuditEvent(
            group_id, user_id, request_id, f"pool_{target}", "pool", pool_id, {}, utcnow()
        )
        if self.database is None:
            raise ApplicationError("INTERNAL_ERROR", "Persistence is not configured", 500)
        def transition_in_transaction(session: Any) -> dict[str, Any] | None:
            changed = self.repos.transition_pool(
                group_id, pool_id, expected, target, user_id, event, session=session
            )
            if not changed:
                return None
            # Read the committed write through the same transaction.  Besides
            # avoiding a stale post-commit read, this keeps the response tied
            # to the state transition which was atomically audited.
            return self.repos.get_pool(group_id, pool_id, session=session)

        document = self.database.run_transaction(transition_in_transaction)
        if not document or not document.get("pools", {}).get(pool_id):
            raise ApplicationError("INVALID_POOL_TRANSITION", "Invalid pool transition", 409)
        return self._public_pool(document["pools"][pool_id], pool_id, group_id, user_id)

    @staticmethod
    def options(payload: dict[str, Any]) -> tuple[str, list[PoolOption]]:
        question = payload.get("question")
        raw = payload.get("options")
        if (not isinstance(question, str) or not question.strip() or len(question.strip()) > 1000
                or not isinstance(raw, list) or len(raw) < 2 or len(raw) > 50):
            raise ApplicationError("VALIDATION_ERROR", "Invalid pool", 422)
        options: list[PoolOption] = []
        ids: set[str] = set()
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"id", "label"}:
                raise ApplicationError("VALIDATION_ERROR", "Invalid pool options", 422)
            oid, label = item["id"], item["label"]
            if (
                not isinstance(oid, str)
                or not oid.strip()
                or len(oid) > 100
                or oid in ids
                or not isinstance(label, str)
                or not label.strip()
                or len(label) > 200
            ):
                raise ApplicationError("VALIDATION_ERROR", "Invalid pool options", 422)
            ids.add(oid)
            options.append(PoolOption(oid, label.strip()))
        return question.strip(), options

    def answer(
        self, group_id: str, pool_id: str, user_id: str, option_id: str, request_id: str
    ) -> None:
        pool = self.pool(group_id, pool_id, user_id)
        if pool.get("status") != "open":
            raise ApplicationError("POOL_NOT_OPEN", "Pool is not open", 409)
        if option_id not in {option["id"] for option in pool.get("options", [])}:
            raise ApplicationError("VALIDATION_ERROR", "Unknown option", 422)
        event = AuditEvent(
            group_id, user_id, request_id, "answer_submitted", "answer", pool_id, {}, utcnow()
        )
        if self.database is None:
            raise ApplicationError("INTERNAL_ERROR", "Persistence is not configured", 500)
        ok = self.database.run_transaction(lambda session: self.repos.submit_answer(
            group_id, pool_id, user_id, option_id, event, session=session))
        if not ok:
            raise ApplicationError("POOL_ALREADY_ANSWERED", "Pool already answered", 409)

    def me(self, user_id: str) -> dict[str, Any]:
        record = self._capability("get_user")(user_id)
        if not record:
            raise ApplicationError("AUTHENTICATION_REQUIRED", "Authentication is required", 401)
        return self.public_user(record)

    def list_groups(self, user_id: str) -> list[dict[str, Any]]:
        groups = self._capability("list_groups_for_user")(user_id)
        # Keep the API projection independent of the SQL row shape. In
        # particular, never expose membership rows or persistence-only fields.
        return [
            {
                "id": str(group["id"]),
                "name": group.get("name"),
                "admin_user_id": group.get("admin_user_id"),
                "member_count": int(group.get("member_count", 0)),
                "created_at": group.get("created_at"),
                "updated_at": group.get("updated_at"),
            }
            for group in groups
        ]

    def search_users(self, substring: str, limit: int = 10) -> dict[str, Any]:
        """Build the deliberately minimal response for username autocomplete."""
        items = self._capability("search_usernames")(substring, limit)
        return {"items": [{"username": str(item["username"])} for item in items]}

    def get_members(
        self, group_id: str, user_id: str, limit: int, cursor: str | None
    ) -> dict[str, Any]:
        self.group_for_member(group_id, user_id)
        page = self._capability("list_members")(group_id, limit, cursor)
        # Membership documents intentionally contain only the referenced user ID.
        # Resolve each user through the user port and apply the public-user
        # allowlist rather than copying persistence fields into the member DTO.
        items = [self._member_response(item) for item in page.get("items", [])]
        result: dict[str, Any] = {"items": items}
        if "next_cursor" in page:
            result["next_cursor"] = page["next_cursor"]
        return result

    def _member_response(
        self, membership: dict[str, Any], user: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        member_id = str(membership["user_id"])
        record = user or self._capability("get_user")(member_id)
        public_user = self.public_user(record or {"id": member_id})
        username = public_user.get("username", membership.get("username"))
        # Email is the only user profile field added to this resource.  Never
        # spread the user record: password hashes and provider/internal fields
        # must remain outside the membership response.
        return {
            "group_id": membership["group_id"],
            "user_id": member_id,
            "email": public_user.get("email"),
            **({"username": username} if username is not None else {}),
            "role": membership.get("role"),
            "created_at": membership.get("created_at"),
        }

    def add_member(
        self, group_id: str, actor: str, selector: str, request_id: str,
        *, selector_type: str = "email",
    ) -> dict[str, Any]:
        self.admin_group(group_id, actor)
        if selector_type == "username":
            user = self._capability("find_user_by_username")(selector)
        elif selector_type == "email":
            user = self._capability("find_user_by_email")(selector)
        else:
            raise ApplicationError("VALIDATION_ERROR", "Invalid member", 422)
        if not user:
            raise ApplicationError("NOT_FOUND", "Resource not found", 404)
        member_id = str(user.get("_id", user.get("id")))
        event = AuditEvent(
            group_id, actor, request_id, "member_added", "member", member_id, {}, utcnow()
        )
        ok = self._capability("add_member")(group_id, member_id, event=event)
        if not ok:
            raise ApplicationError("CONFLICT", "Membership already exists", 409)
        return self._member_response({
            "group_id": group_id, "user_id": member_id, "role": "member",
            "created_at": event.occurred_at,
        }, user)

    def remove_member(self, group_id: str, actor: str, member_id: str, request_id: str) -> None:
        self.admin_group(group_id, actor)
        if member_id == actor:
            raise ApplicationError("CONFLICT", "The group admin cannot be removed", 409)
        event = AuditEvent(
            group_id, actor, request_id, "member_removed", "member", member_id, {}, utcnow()
        )
        if not self._capability("remove_member")(group_id, member_id, event=event):
            raise ApplicationError("NOT_FOUND", "Resource not found", 404)
