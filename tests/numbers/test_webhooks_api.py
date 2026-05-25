import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.platform import webhooks_api
from services.platform.api_auth import ApiAuthContext
from services.platform.api_rate_limits import ApiRateLimitDecision


async def allow_rate_limit(auth, *, bucket, limit, window_seconds=60):
    return ApiRateLimitDecision(bucket=bucket, limit=limit, remaining=limit - 1, reset_at=9999999999, window_seconds=60)


def test_register_webhook_routes_adds_endpoints():
    app = web.Application()

    webhooks_api.register_webhook_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/webhooks") in routes
    assert ("POST", "/api/v1/webhooks") in routes
    assert ("POST", "/api/v1/webhooks/{webhook_id}/revoke") in routes


@pytest.mark.asyncio
async def test_create_webhook_endpoint_returns_secret_once(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return ApiAuthContext(key_id="key-1", user_id=123, reseller_id=456, scopes=("webhooks:manage",))

    async def fake_create_webhook(**kwargs):
        calls["create"] = kwargs
        return "whsec_secret", {
            "_id": "hook-1",
            "url": kwargs["url"],
            "events": kwargs["events"],
            "status": "active",
        }

    monkeypatch.setattr(webhooks_api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(webhooks_api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(webhooks_api, "create_webhook", fake_create_webhook)
    request = make_mocked_request("POST", "/api/v1/webhooks", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps(
        {"url": "https://example.com/webhook", "events": ["numbers.order.sms", "numbers.order.resend_requested", "not.allowed"]}
    ).encode("utf-8")

    response = await webhooks_api.create_webhook_endpoint(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls["auth_scope"] == "webhooks:manage"
    assert calls["create"] == {
        "user_id": 123,
        "reseller_id": 456,
        "url": "https://example.com/webhook",
        "events": ["numbers.order.resend_requested", "numbers.order.sms"],
    }
    assert payload["secret"] == "whsec_secret"
    assert response.headers["X-RateLimit-Bucket"] == "webhooks:manage"


@pytest.mark.asyncio
async def test_create_webhook_endpoint_rejects_non_https(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return ApiAuthContext(key_id="key-1", user_id=123, reseller_id=456, scopes=("webhooks:manage",))

    monkeypatch.setattr(webhooks_api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(webhooks_api, "check_api_rate_limit", allow_rate_limit)
    request = make_mocked_request("POST", "/api/v1/webhooks", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"url": "http://example.com/webhook", "events": ["numbers.order.sms"]}).encode("utf-8")

    response = await webhooks_api.create_webhook_endpoint(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "invalid_webhook_url"
