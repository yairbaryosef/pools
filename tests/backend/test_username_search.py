from __future__ import annotations

import httpx
import pytest

from atlas.api import create_app


class _Repositories:
    def get_active_session(self, token_hash: str):
        return {"user_id": "caller"} if token_hash else None

    def search_usernames(self, substring: str, limit: int = 10):
        assert substring == "al"
        assert limit == 10
        return [{"username": "Alice"}, {"username": "Sally"}]


@pytest.mark.asyncio
async def test_username_search_is_authenticated_and_exposes_only_usernames() -> None:
    app = create_app(repositories=_Repositories())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/v1/users/search?username=al")
        assert denied.status_code == 401

        response = await client.get(
            "/v1/users/search?username=al", cookies={"atlas_session": "session"}
        )
    assert response.status_code == 200
    assert response.json() == {"items": [{"username": "Alice"}, {"username": "Sally"}]}
    assert "email" not in response.text


@pytest.mark.asyncio
async def test_username_search_rejects_blank_or_extra_query_parameters() -> None:
    app = create_app(repositories=_Repositories())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for query in ("username=", "username=al&limit=100"):
            response = await client.get(
                f"/v1/users/search?{query}", cookies={"atlas_session": "session"}
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"
