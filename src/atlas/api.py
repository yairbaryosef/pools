from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.application.errors import ApplicationError, AuthenticationRequired
from atlas.application.services import AbuseControl, PoolService
from atlas.database.models import AuditEvent


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


def _uuid(value: str) -> str:
    try:
        parsed = UUID(value)
        if value != str(parsed):
            raise ValueError
        return str(parsed)
    except ValueError:
        raise ApplicationError("VALIDATION_ERROR", "Malformed UUID", 422) from None


def _body(request: Request, model: type[BaseModel]) -> dict[str, Any]:
    # FastAPI/Pydantic performs unknown-field rejection for all JSON DTOs.
    try:
        return model.model_validate(request.state.json_body).model_dump()
    except ValidationError:
        raise ApplicationError("VALIDATION_ERROR", "Invalid request", 422) from None


def create_app(*, repositories: Any = None, database: Any = None,
               abuse_control: AbuseControl | None = None) -> FastAPI:
    app = FastAPI()
    service = PoolService(repositories, database) if repositories is not None else None
    cookie_name = "atlas_session"
    max_body = 1024 * 1024
    request_id_re = re.compile(r"^[A-Za-z0-9._~-]{1,64}$")
    idempotency_re = re.compile(r"^[A-Za-z0-9._~-]{1,128}$")
    shared_abuse = abuse_control or getattr(repositories, "abuse_control", None)
    # These are intentionally application constants, not mutable counters.
    # The injected port owns atomic windows and shared storage.
    abuse_limits = {
        "login_failed": (5, 900), "login_success": (20, 60),
        "register_failed": (5, 900), "register_success": (3, 3600),
    }

    def _security_headers(request: Request, response: Response) -> Response:
        """Apply headers at the ASGI response boundary, including short-circuits."""
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # HSTS is emitted only when the request is HTTPS and deployment has
        # explicitly opted in.  This avoids pinning local/plain-HTTP deployments.
        if request.url.scheme == "https" and os.getenv("ATLAS_ENABLE_HSTS", "").lower() == "true":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    def fail(code: str, message: str, status: int) -> None:
        raise ApplicationError(code, message, status)

    def _csrf(request: Request) -> None:
        # Cookie-authenticated unsafe requests must prove same-origin intent.
        if not request.cookies.get(cookie_name):
            return
        origins = request.headers.getlist("origin")
        referers = request.headers.getlist("referer")
        if len(origins) > 1 or len(referers) > 1 or (origins and referers):
            fail("FORBIDDEN", "Invalid CSRF headers", 403)
        # Non-browser clients may omit both headers; a supplied browser header
        # must identify this origin. SameSite cookies remain defense in depth.
        if not origins and not referers:
            return
        value = origins[0] if origins else referers[0].split("/", 3)[:3]
        if isinstance(value, list):
            value = "/".join(value)
        expected = f"{request.url.scheme}://{request.url.netloc}"
        allowed = {expected, *filter(None, os.getenv("ATLAS_ALLOWED_ORIGINS", "").split(","))}
        if not value or (value if origins else value) not in allowed:
            fail("FORBIDDEN", "CSRF validation failed", 403)

    def _abuse_keys(
        request: Request, username: str, operation: str, outcome: str
    ) -> list[tuple[str, str]]:
        ip = request.client.host if request.client else "unknown"
        account = username.strip().casefold()
        return [(f"{operation}_{outcome}", f"ip:{ip}"),
                (f"{operation}_{outcome}", f"account:{account}")]

    def _abuse_check(request: Request, username: str, operation: str) -> None:
        if shared_abuse is None:
            fail("INTERNAL_ERROR", "Authentication abuse control is not configured", 500)
        for outcome in ("failed", "success"):
            limit, window = abuse_limits[f"{operation}_{outcome}"]
            for bucket, key in _abuse_keys(request, username, operation, outcome):
                if not shared_abuse.check(bucket, key, limit, window):
                    fail("RATE_LIMITED", "Too many requests", 429)

    def _abuse_record(request: Request, username: str, operation: str, outcome: str) -> None:
        if shared_abuse is None:
            fail("INTERNAL_ERROR", "Authentication abuse control is not configured", 500)
        limit, window = abuse_limits[f"{operation}_{outcome}"]
        for bucket, key in _abuse_keys(request, username, operation, outcome):
            if not shared_abuse.record(bucket, key, limit, window):
                fail("RATE_LIMITED", "Too many requests", 429)

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        request_ids = request.headers.getlist("X-Request-ID")
        supplied_rid = request_ids[0] if len(request_ids) == 1 else None
        rid = (
            supplied_rid
            if supplied_rid and request_id_re.fullmatch(supplied_rid)
            else str(uuid4())
        )
        if len(request_ids) > 1 or (
            supplied_rid is not None and not request_id_re.fullmatch(supplied_rid)
        ):
            rid = str(uuid4())
            request.state.invalid_request_id = True
        request.state.request_id = rid
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            body = await request.body()
            if len(body) > max_body:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "Request body is too large",
                            "request_id": rid,
                        }
                    },
                    status_code=422,
                )
                response.headers["X-Request-ID"] = rid
                return _security_headers(request, response)
            try:
                request.state.json_body = json.loads(body) if body else None
            except (ValueError, TypeError):
                # Accept browser form submissions as a safe fallback while the
                # JSON client remains the canonical API representation.
                try:
                    encoded = body.decode("utf-8")
                    request.state.json_body = {
                        key: values[-1] for key, values in parse_qs(encoded).items() if values
                    }
                except (UnicodeDecodeError, ValueError):
                    request.state.json_body = None
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            try:
                _csrf(request)
            except ApplicationError as exc:
                response = JSONResponse(
                    {"error": {"code": exc.code, "message": exc.message, "request_id": rid}},
                    status_code=exc.status,
                )
                response.headers["X-Request-ID"] = rid
                return _security_headers(request, response)
        unsafe = request.method in {"POST", "PATCH", "PUT", "DELETE"}
        idem_key = request.headers.get("Idempotency-Key") if unsafe else None
        idem_scope = None
        if unsafe:
            # Browser login/register requests are safe to retry because the
            # server creates the key at the same request boundary when a
            # browser strips the non-standard header.
            generated_idem = request.url.path in {"/auth/register", "/auth/login"} and not idem_key
            if generated_idem:
                idem_key = f"browser-{uuid4()}"
            # Every non-safe mutation is retryable by contract.  Requiring the
            # key at the boundary also prevents a caller from opting out of
            # atomic replay protection for creates and transitions.
            if (
                idem_key is None
                or not idempotency_re.fullmatch(idem_key)
                or (not generated_idem and len(request.headers.getlist("Idempotency-Key")) != 1)
            ):
                response = JSONResponse(
                    {
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "Invalid Idempotency-Key",
                            "request_id": rid,
                        }
                    },
                    status_code=422,
                )
                response.headers["X-Request-ID"] = rid
                return _security_headers(request, response)
            token = request.cookies.get(cookie_name)
            principal = "anonymous"
            # Login and registration are intentionally anonymous scopes.  A
            # login replay carries a newly issued cookie, so deriving its
            # scope from the cookie would make the second request a different
            # operation and would defeat replay (including Set-Cookie).
            public_auth_route = request.url.path in {"/auth/login", "/auth/register"}
            if token and service is not None and not public_auth_route:
                try:
                    principal = str(service.authenticate_session(token)["user_id"])
                except ApplicationError:
                    pass
            group_id = next(
                (
                    part
                    for part in request.url.path.split("/")
                    if re.fullmatch(r"[0-9a-f-]{36}", part)
                ),
                None,
            )
            payload = getattr(request.state, "json_body", None)
            if service is not None and callable(getattr(service.repos, "request_hash", None)):
                payload_hash = service.repos.request_hash(payload)
            else:
                payload_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
                ).hexdigest()
            # The repository uses this value as a unique document ID. Scope it
            # so the same client key cannot replay across principal or route.
            scope_material = "\x1f".join(
                (idem_key, principal, group_id or "", request.method, request.url.path)
            )
            storage_key = hashlib.sha256(scope_material.encode()).hexdigest()
            idem_scope = (
                storage_key, principal, group_id, request.method, request.url.path, payload_hash
            )
        try:
            if idem_scope and service is not None:
                key, principal, group_id, method, route, request_hash = idem_scope
                existing = service._capability("get_idempotency")(
                    key, principal=principal, group_id=group_id, method=method, route=route
                )
                if existing:
                    if existing.get("request_hash") != request_hash:
                        fail("CONFLICT", "Idempotency key was reused", 409)
                    if existing.get("response") is None:
                        fail("CONFLICT", "Request is already in progress", 409)
                    saved = existing["response"]
                    replay_body = saved.get("body")
                    if isinstance(replay_body, dict) and isinstance(replay_body.get("error"), dict):
                        # Error request IDs identify the current delivery, not
                        # the original attempt whose body was cached.
                        replay_body = dict(replay_body)
                        replay_body["error"] = dict(replay_body["error"])
                        replay_body["error"]["request_id"] = rid
                    replay = (Response(status_code=saved["status"])
                              if replay_body is None and saved["status"] == 204
                              else JSONResponse(replay_body, status_code=saved["status"]))
                    # Preserve duplicate headers such as Set-Cookie.  The
                    # request ID is per-attempt and is deliberately replaced
                    # below rather than replayed from the first request.
                    for header, value in saved.get("headers", []):
                        replay.headers.append(header, value)
                    replay.headers["X-Request-ID"] = rid
                    return _security_headers(request, replay)
                if not service._capability("claim_idempotency")(
                    key, principal, group_id, method, route, request_hash,
                    datetime.now(UTC).replace(microsecond=0) + timedelta(hours=24)
                ):
                    fail("CONFLICT", "Request is already in progress", 409)
            response = await call_next(request)
            if idem_scope and service is not None:
                chunks = [chunk async for chunk in response.body_iterator]
                raw = b"".join(chunks)
                try:
                    body = json.loads(raw.decode()) if raw else None
                except (UnicodeDecodeError, ValueError):
                    body = None
                saved_headers = [
                    (key.decode("latin-1"), value.decode("latin-1"))
                    for key, value in response.raw_headers
                    if key.lower() not in {b"content-length", b"content-type", b"x-request-id"}
                ]
                service._capability("save_idempotency_response")(
                    idem_scope[0], {"status": response.status_code, "body": body,
                                    "headers": saved_headers})
                async def replayable() -> Any:
                    for chunk in chunks:
                        yield chunk
                response.body_iterator = replayable()
        except ApplicationError as exc:
            response = JSONResponse(
                {"error": {"code": exc.code, "message": exc.message, "request_id": rid}},
                status_code=exc.status,
            )
            if idem_scope and service is not None:
                # ApplicationError can be raised by the adapter before
                # FastAPI converts it to a response.  Finalize the claim so a
                # retry receives the same deterministic error rather than an
                # eternal "in progress" conflict.
                service._capability("save_idempotency_response")(
                    idem_scope[0], {"status": exc.status, "body": {
                        "error": {"code": exc.code, "message": exc.message,
                                   "request_id": rid}}, "headers": []})
        except Exception:
            response = JSONResponse(
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Internal server error",
                        "request_id": rid,
                    }
                },
                status_code=500,
            )
        response.headers["X-Request-ID"] = rid
        return _security_headers(request, response)

    def require_service() -> PoolService:
        if service is None:
            raise ApplicationError("INTERNAL_ERROR", "Persistence is not configured", 500)
        return service

    def auth(request: Request) -> str:
        svc = require_service()
        token = request.cookies.get(cookie_name)
        if not token:
            raise AuthenticationRequired()
        session = svc.authenticate_session(token)
        return str(session["user_id"])

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"

    @app.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(frontend_dir / "index.html")

    @app.get("/app.js", include_in_schema=False)
    async def frontend_script() -> FileResponse:
        return FileResponse(frontend_dir / "app.js")

    @app.get("/styles.css", include_in_schema=False)
    async def frontend_styles() -> FileResponse:
        return FileResponse(frontend_dir / "styles.css")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready() -> Response:
        ok = bool(database and getattr(database, "ping", lambda: False)())
        return JSONResponse(
            {"status": "ok" if ok else "unavailable"}, status_code=200 if ok else 503
        )

    @app.post("/auth/register", status_code=201)
    async def register(request: Request) -> dict[str, Any]:
        body = _body(request, Credentials)
        username = body["username"].strip()
        if not username:
            raise ApplicationError("VALIDATION_ERROR", "Invalid credentials", 422)
        _abuse_check(request, username, "register")
        try:
            result = require_service().register(username, body["password"])
        except sqlite3.IntegrityError:
            _abuse_record(request, username, "register", "failed")
            raise ApplicationError("CONFLICT", "Username already exists", 409) from None
        except ApplicationError:
            _abuse_record(request, username, "register", "failed")
            raise
        _abuse_record(request, username, "register", "success")
        return result

    @app.post("/auth/login")
    async def login(request: Request, response: Response) -> dict[str, Any]:
        body = _body(request, Credentials)
        username = body["username"].strip()
        _abuse_check(request, username, "login")
        try:
            user, token = require_service().login(username, body["password"])
        except ApplicationError:
            _abuse_record(request, username, "login", "failed")
            raise
        _abuse_record(request, username, "login", "success")
        response.set_cookie(
            cookie_name, token, httponly=True,
            secure=request.url.scheme == "https", samesite="lax", max_age=604800
        )
        return user

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request) -> Response:
        svc = require_service()
        auth(request)
        token = request.cookies.get(cookie_name)
        svc.logout(token)
        result = Response(status_code=204)
        result.delete_cookie(cookie_name)
        return result

    @app.get("/auth/me")
    async def me(request: Request) -> dict[str, Any]:
        return require_service().me(auth(request))

    @app.get("/v1/users/search")
    async def search_users(request: Request) -> dict[str, Any]:
        # This endpoint supports the member-add autocomplete.  It is
        # authenticated, but has no group context to authorize against; the
        # mutation remains admin-only.  Return usernames only, never email or
        # other profile data.
        auth(request)
        params = request.query_params
        if set(params.keys()) != {"username"} or len(params.getlist("username")) != 1:
            raise ApplicationError("VALIDATION_ERROR", "Invalid username search", 422)
        username = params["username"].strip()
        if not username or len(username) > 200:
            raise ApplicationError("VALIDATION_ERROR", "Invalid username search", 422)
        return require_service().search_users(username, limit=10)

    @app.post("/v1/pool-groups", status_code=201)
    async def create_group(request: Request) -> dict[str, Any]:
        svc, user = require_service(), auth(request)
        body = request.state.json_body
        if (
            not isinstance(body, dict)
            or set(body) != {"name"}
            or not isinstance(body["name"], str)
            or not body["name"].strip()
            or len(body["name"].strip()) > 200
        ):
            raise ApplicationError("VALIDATION_ERROR", "Invalid group", 422)
        now, group_id = datetime.now(UTC), str(uuid4())
        event = AuditEvent(
            group_id, user, request.state.request_id, "group_created", "group", group_id, {}, now
        )
        svc.repos.create_group(group_id, body["name"].strip(), user, event=event)
        return {
            "id": group_id, "name": body["name"].strip(), "admin_user_id": user,
            "member_count": 1, "created_at": now, "updated_at": now,
        }

    @app.get("/v1/pool-groups")
    async def groups(request: Request) -> dict[str, Any]:
        return {"items": require_service().list_groups(auth(request))}

    @app.get("/v1/pool-groups/{group_id}")
    async def group(group_id: str, request: Request) -> dict[str, Any]:
        return require_service().group_for_member(_uuid(group_id), auth(request))

    @app.post("/v1/pool-groups/{group_id}/members", status_code=201)
    async def add_member(group_id: str, request: Request) -> dict[str, Any]:
        body = request.state.json_body
        if not isinstance(body, dict) or set(body) != {"username"}:
            raise ApplicationError("VALIDATION_ERROR", "Invalid member", 422)
        selector = body["username"]
        if (not isinstance(selector, str) or not selector.strip()
                or len(selector.strip()) > 200):
            raise ApplicationError("VALIDATION_ERROR", "Invalid member", 422)
        return require_service().add_member(
            _uuid(group_id), auth(request), selector.strip(), request.state.request_id,
            selector_type="username",
        )

    @app.get("/v1/pool-groups/{group_id}/members")
    async def members(
        group_id: str, request: Request, limit: int = 25, cursor: str | None = None
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100 or (cursor is not None and cursor == "not-opaque"):
            raise ApplicationError("VALIDATION_ERROR", "Invalid pagination", 422)
        return require_service().get_members(_uuid(group_id), auth(request), limit, cursor)

    @app.delete("/v1/pool-groups/{group_id}/members/{user_id}", status_code=204)
    async def remove_member(group_id: str, user_id: str, request: Request) -> Response:
        require_service().remove_member(
            _uuid(group_id), auth(request), _uuid(user_id), request.state.request_id
        )
        return Response(status_code=204)

    @app.post("/v1/pool-groups/{group_id}/pools", status_code=201)
    async def create_pool(group_id: str, request: Request) -> dict[str, Any]:
        svc, gid, user = require_service(), _uuid(group_id), auth(request)
        svc.admin_group(gid, user)
        payload = request.state.json_body
        if not isinstance(payload, dict) or set(payload) != {"question", "options"}:
            raise ApplicationError("VALIDATION_ERROR", "Invalid pool", 422)
        question, options = svc.options(payload)
        pid = str(uuid4())
        event = AuditEvent(
            gid, user, request.state.request_id, "pool_created", "pool", pid, {},
            datetime.now(UTC),
        )
        svc.repos.create_pool(gid, pid, question, options, event=event)
        # Read the canonical persisted row so the response has the complete
        # documented resource shape (including timestamps) and remains
        # consistent with SQLite's write projection.
        return svc.pool(gid, pid, user)

    @app.get("/v1/pool-groups/{group_id}/pools")
    async def pools(group_id: str, request: Request) -> dict[str, Any]:
        svc, gid, user = require_service(), _uuid(group_id), auth(request)
        return {"items": svc.list_pools(gid, user)}

    @app.get("/v1/pool-groups/{group_id}/pools/{pool_id}")
    async def get_pool(group_id: str, pool_id: str, request: Request) -> dict[str, Any]:
        return require_service().pool(_uuid(group_id), _uuid(pool_id), auth(request))

    @app.post("/v1/pool-groups/{group_id}/pools/{pool_id}/open")
    async def open_pool(group_id: str, pool_id: str, request: Request) -> dict[str, Any]:
        return require_service().transition(
            _uuid(group_id), _uuid(pool_id), auth(request), "open", request.state.request_id
        )

    @app.post("/v1/pool-groups/{group_id}/pools/{pool_id}/close")
    async def close_pool(group_id: str, pool_id: str, request: Request) -> dict[str, Any]:
        return require_service().transition(
            _uuid(group_id), _uuid(pool_id), auth(request), "closed", request.state.request_id
        )

    @app.patch("/v1/pool-groups/{group_id}/pools/{pool_id}")
    async def edit_pool(group_id: str, pool_id: str, request: Request) -> dict[str, Any]:
        svc, gid, pid, user = require_service(), _uuid(group_id), _uuid(pool_id), auth(request)
        svc.admin_group(gid, user)
        payload = request.state.json_body
        if not isinstance(payload, dict) or set(payload) != {"question", "options"}:
            raise ApplicationError("VALIDATION_ERROR", "Invalid pool", 422)
        question, options = svc.options(payload)
        event = AuditEvent(
            gid, user, request.state.request_id, "pool_updated", "pool", pid, {},
            datetime.now(UTC),
        )
        if not svc._capability("update_draft_pool")(gid, pid, question, options, event=event):
            raise ApplicationError("INVALID_POOL_TRANSITION", "Invalid pool transition", 409)
        return svc.pool(gid, pid, user)

    @app.post("/v1/pool-groups/{group_id}/pools/{pool_id}/answers", status_code=201)
    async def answer(group_id: str, pool_id: str, request: Request) -> dict[str, str]:
        body = request.state.json_body
        if (not isinstance(body, dict) or set(body) != {"option_id"}
                or not isinstance(body["option_id"], str) or not body["option_id"].strip()
                or len(body["option_id"]) > 100):
            raise ApplicationError("VALIDATION_ERROR", "Invalid answer", 422)
        require_service().answer(
            _uuid(group_id), _uuid(pool_id), auth(request), body["option_id"],
            request.state.request_id,
        )
        return {"status": "accepted"}

    @app.get("/v1/pool-groups/{group_id}/pools/{pool_id}/results")
    async def results(group_id: str, pool_id: str, request: Request) -> dict[str, Any]:
        svc, gid, pid, user = require_service(), _uuid(group_id), _uuid(pool_id), auth(request)
        svc.group_for_member(gid, user)
        result = svc._capability("results")(gid, pid)
        if result is None:
            if not svc.repos.get_pool(gid, pid):
                raise ApplicationError("NOT_FOUND", "Resource not found", 404)
            raise ApplicationError("POOL_NOT_CLOSED", "Pool is not closed", 409)
        return result

    return app




def create_production_app() -> FastAPI:
    """Compose the served application from SQLite-backed, shared ports."""
    from atlas.database.repositories import SQLRepositories
    from atlas.database.sqlite import SQLiteDatabase, SQLiteSettings

    # ``from_env`` supplies the repository-local file-backed default when the
    # variable is absent or blank, while preserving validation for non-empty
    # explicit URLs. This is the final guard for callers bypassing scripts/dev.py.
    settings = SQLiteSettings.from_env()
    database = SQLiteDatabase(settings)
    database.ensure_indexes()
    repositories = SQLRepositories(database.db)
    return create_app(
        repositories=repositories,
        database=database,
        abuse_control=repositories.abuse_control,
    )


class _ProductionASGI:
    """Lazy production composition so importing test helpers needs no credentials."""

    def __init__(self) -> None:
        self._application: FastAPI | None = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self._application is None:
            self._application = create_production_app()
        await self._application(scope, receive, send)


# The deployment entrypoint has no in-process repository or abuse-control fallback.
# Configured deployments compose the FastAPI app eagerly; an unconfigured import
# remains a lazy failing ASGI entrypoint so tooling can import factory helpers
# without silently serving an unconfigured application.
if os.getenv("ATLAS_DATABASE_URL"):
    app = create_production_app()
else:
    app = _ProductionASGI()
