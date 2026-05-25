import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.platform import api_keys_api
from services.platform.api_auth import ApiAuthContext


def test_register_api_key_routes_adds_management_endpoints():
    app = web.Application()

    api_keys_api.register_api_key_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/api-keys") in routes
    assert ("POST", "/api/v1/api-keys") in routes
    assert ("POST", "/api/v1/api-keys/{key_id}/revoke") in routes


@pytest.mark.asyncio
async def test_create_key_filters_to_allowed_customer_scopes(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return ApiAuthContext(key_id="manager", user_id=123, reseller_id=123, scopes=("api_keys:manage",))

    async def fake_create_api_key(**kwargs):
        calls["create"] = kwargs
        return "ph_live_secret", {
            "_id": "key-1",
            "prefix": "ph_live_sec",
            "user_id": kwargs["user_id"],
            "reseller_id": kwargs["reseller_id"],
            "name": kwargs["name"],
            "scopes": kwargs["scopes"],
            "status": "active",
        }

    monkeypatch.setattr(api_keys_api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api_keys_api, "create_api_key", fake_create_api_key)
    request = make_mocked_request("POST", "/api/v1/api-keys", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps(
        {"name": "bot", "scopes": ["numbers:quotes", "api_keys:manage", "numbers:orders:create"]}
    ).encode("utf-8")

    response = await api_keys_api.create_key(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "api_keys:manage"
    assert calls["create"]["user_id"] == 123
    assert calls["create"]["reseller_id"] == 123
    assert calls["create"]["scopes"] == ["numbers:orders:create", "numbers:quotes"]
    assert payload["api_key"] == "ph_live_secret"
    assert "key_hash" not in payload["key"]


@pytest.mark.asyncio
async def test_create_key_requires_valid_scope(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return ApiAuthContext(key_id="manager", user_id=123, reseller_id=123, scopes=("api_keys:manage",))

    monkeypatch.setattr(api_keys_api, "require_api_auth", fake_require_api_auth)
    request = make_mocked_request("POST", "/api/v1/api-keys", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"scopes": ["api_keys:manage"]}).encode("utf-8")

    response = await api_keys_api.create_key(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "missing_scopes"


@pytest.mark.asyncio
async def test_list_keys_is_reseller_scoped(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return ApiAuthContext(key_id="manager", user_id=123, reseller_id=456, scopes=("api_keys:manage",))

    async def fake_list_api_keys(**kwargs):
        calls["list"] = kwargs
        return [{"id": "key-1", "status": "active"}]

    monkeypatch.setattr(api_keys_api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api_keys_api, "list_api_keys", fake_list_api_keys)
    request = make_mocked_request("GET", "/api/v1/api-keys")

    response = await api_keys_api.list_keys(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "api_keys:manage"
    assert calls["list"] == {"reseller_id": 456}
    assert payload["keys"] == [{"id": "key-1", "status": "active"}]


@pytest.mark.asyncio
async def test_revoke_key_scopes_to_reseller_without_super_key(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        return ApiAuthContext(key_id="manager", user_id=123, reseller_id=456, scopes=("api_keys:manage",))

    async def fake_revoke_api_key(**kwargs):
        calls["revoke"] = kwargs
        return True

    monkeypatch.setattr(api_keys_api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api_keys_api, "revoke_api_key", fake_revoke_api_key)
    request = make_mocked_request("POST", "/api/v1/api-keys/key-1/revoke")
    request.match_info["key_id"] = "key-1"

    response = await api_keys_api.revoke_key(request)
    payload = json.loads(response.text)

    assert calls["revoke"] == {"key_id": "key-1", "reseller_id": 456}
    assert payload == {"ok": True, "id": "key-1", "status": "revoked"}
