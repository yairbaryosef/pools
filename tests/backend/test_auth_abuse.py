from __future__ import annotations

from collections import defaultdict

from fastapi.testclient import TestClient

from atlas.api import create_app
from atlas.application.services import PoolService


class SharedAbuse:
    def __init__(self) -> None:
        self.counts: defaultdict[tuple[str, str], int] = defaultdict(int)

    def check(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        return self.counts[(bucket, key)] < limit

    def record(self, bucket: str, key: str, limit: int, window_seconds: int) -> bool:
        if not self.check(bucket, key, limit, window_seconds):
            return False
        self.counts[(bucket, key)] += 1
        return True


class Repo:
    def __init__(self) -> None:
        self.user = {"_id": "user-1", "username": "alice",
                     "password_hash": PoolService.hash_password("correct")}
        self.session_user_id = None

    def find_user_by_username(self, username: str):
        return self.user if username.casefold() == "alice" else None

    def create_password_user(self, user_id, username, password_hash, now):
        return {"_id": user_id, "username": username, "created_at": now}

    def create_session(self, *args):
        self.session_user_id = args[1]

    def get_active_session(self, token_hash):
        return {"user_id": self.session_user_id} if self.session_user_id else None

    def get_user(self, user_id):
        return self.user if user_id == self.user["_id"] else None

    def request_hash(self, payload):
        return "0" * 64

    def get_idempotency(self, *args, **kwargs):
        return None

    def claim_idempotency(self, *args, **kwargs):
        return True

    def save_idempotency_response(self, *args, **kwargs):
        return True


def check(condition: bool, message: str = "") -> None:
    if not condition:
        raise AssertionError(message)


def test_login_failed_limits_are_shared_by_ip_and_account() -> None:
    app = create_app(repositories=Repo(), abuse_control=SharedAbuse())
    with TestClient(app) as client:
        for attempt in range(5):
            response = client.post("/auth/login", json={"username": "alice", "password": "wrong"},
                                   headers={"Idempotency-Key": f"failed-{attempt}"})
            check(response.status_code == 401)
        response = client.post("/auth/login", json={"username": "alice", "password": "wrong"},
                               headers={"Idempotency-Key": "failed-6"})
        check(response.status_code == 429)
        check(response.json()["error"]["code"] == "RATE_LIMITED")


def test_register_success_limit_returns_429() -> None:
    app = create_app(repositories=Repo(), abuse_control=SharedAbuse())
    with TestClient(app) as client:
        for attempt in range(3):
            response = client.post(
                "/auth/register",
                # Different accounts must still share the per-IP registration
                # success budget.  This mirrors isolated E2E users and guards
                # against accidentally making the account key the only limit.
                json={"username": f"new-user-{attempt}", "password": "password"},
                headers={"Idempotency-Key": f"register-{attempt}"},
            )
            check(response.status_code == 201)
        response = client.post(
            "/auth/register",
            json={"username": "new-user-unique", "password": "password"},
            headers={"Idempotency-Key": "register-4"},
        )
        check(response.status_code == 429)


def test_unknown_login_still_uses_bounded_dummy_verification() -> None:
    check(PoolService.verify_password("wrong", PoolService.dummy_password_hash()) is False)


def test_password_auth_responses_have_stable_ids_without_password_fields() -> None:
    repo = Repo()
    app = create_app(repositories=repo, abuse_control=SharedAbuse())
    with TestClient(app) as client:
        registered = client.post(
            "/auth/register",
            json={"username": "new-user", "password": "password"},
            headers={"Idempotency-Key": "auth-register-id"},
        )
        check(registered.status_code == 201)
        registered_body = registered.json()
        check(registered_body["id"])
        check(registered_body["username"] == "new-user")
        check("password" not in registered_body)
        check("password_hash" not in registered_body)

        logged_in = client.post(
            "/auth/login",
            json={"username": "alice", "password": "correct"},
            headers={"Idempotency-Key": "auth-login-id"},
        )
        check(logged_in.status_code == 200)
        login_body = logged_in.json()
        check(login_body == {"id": "user-1", "username": "alice"})

        current = client.get("/auth/me")
        check(current.status_code == 200)
        check(current.json() == {"id": "user-1", "username": "alice"})
