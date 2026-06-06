import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from database import api_keys_repo
from services.platform import api_auth


def test_api_key_hash_does_not_store_raw_secret():
    key = "ph_live_secret"

    digest = api_keys_repo.hash_api_key(key)

    assert digest != key
    assert api_keys_repo.constant_time_key_match(key, digest) is True
    assert api_keys_repo.constant_time_key_match("wrong", digest) is False


@pytest.mark.asyncio
async def test_require_api_auth_accepts_bearer_key(monkeypatch):
    calls = {}

    async def fake_find_active_api_key(key):
        calls["key"] = key
        return {
            "_id": "api-key-1",
            "user_id": 123,
            "reseller_id": 456,
            "scopes": ["numbers:quotes"],
            "name": "customer",
        }

    monkeypatch.setattr(api_auth, "find_active_api_key", fake_find_active_api_key)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes", headers={"Authorization": "Bearer ph_live_abc"})

    ctx = await api_auth.require_api_auth(request, "numbers:quotes")

    assert calls["key"] == "ph_live_abc"
    assert ctx.user_id == 123
    assert ctx.reseller_id == 456
    assert ctx.scopes == ("numbers:quotes",)


@pytest.mark.asyncio
async def test_require_api_auth_rejects_missing_scope(monkeypatch):
    async def fake_find_active_api_key(_key):
        return {"_id": "api-key-1", "user_id": 123, "reseller_id": 123, "scopes": ["numbers:quotes"]}

    monkeypatch.setattr(api_auth, "find_active_api_key", fake_find_active_api_key)
    request = make_mocked_request("POST", "/api/v1/numbers/orders", headers={"X-API-Key": "ph_live_abc"})

    with pytest.raises(web.HTTPForbidden):
        await api_auth.require_api_auth(request, "numbers:orders:create")


@pytest.mark.asyncio
async def test_require_api_auth_allows_wildcard_scope(monkeypatch):
    async def fake_find_active_api_key(_key):
        return {"_id": "api-key-1", "user_id": 123, "reseller_id": 123, "scopes": ["*"]}

    monkeypatch.setattr(api_auth, "find_active_api_key", fake_find_active_api_key)
    request = make_mocked_request("POST", "/api/v1/numbers/orders", headers={"X-API-Key": "ph_live_abc"})

    ctx = await api_auth.require_api_auth(request, "numbers:orders:create")

    assert ctx.user_id == 123


@pytest.mark.asyncio
async def test_require_api_auth_rejects_unverified_website_session(monkeypatch):
    async def unverified(_request):
        raise web.HTTPForbidden(text="email verification required")

    import services.platform.website_auth as website_auth

    monkeypatch.setattr(website_auth, "require_website_email_verified", unverified)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes")

    with pytest.raises(web.HTTPForbidden):
        await api_auth.require_api_auth(request, "numbers:quotes")
