import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.numbers import api
from services.numbers import api_payloads
from services.platform.api_auth import ApiAuthContext
from services.platform.api_rate_limits import ApiRateLimitDecision


def api_auth_context(**kwargs):
    return ApiAuthContext(**kwargs)


async def allow_rate_limit(auth, *, bucket, limit, window_seconds=60):
    return ApiRateLimitDecision(bucket=bucket, limit=limit, remaining=limit - 1, reset_at=9999999999, window_seconds=60)


def test_register_numbers_api_routes_adds_versioned_endpoints():
    app = web.Application()

    api.register_numbers_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/numbers/health") in routes
    assert ("GET", "/api/v1/numbers/catalog/bootstrap") in routes
    assert ("GET", "/api/v1/numbers/quotes") in routes
    assert ("POST", "/api/v1/numbers/orders") in routes


@pytest.mark.asyncio
async def test_numbers_api_health():
    request = make_mocked_request("GET", "/api/v1/numbers/health")

    response = await api.health(request)
    payload = json.loads(response.text)

    assert payload == {
        "ok": True,
        "status": "healthy",
        "service": "numbers-api",
        "version": "v1",
    }


@pytest.mark.asyncio
async def test_numbers_api_catalog_bootstrap_has_core_selectors():
    api_payloads.clear_numbers_api_payload_cache()
    request = make_mocked_request("GET", "/api/v1/numbers/catalog/bootstrap")

    response = await api.catalog_bootstrap(request)
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["version"] == "v1"
    assert payload["defaults"] == {"mode": "temp", "service": "", "country": "none", "state": "none"}
    assert [item["key"] for item in payload["modes"]] == ["temp", "rental", "voice"]
    assert any(item["key"] == "telegram" for item in payload["services"])
    assert any(item["code"] == "1" for item in payload["countries"])
    assert any(item["code"] == "none" for item in payload["states_us"])


@pytest.mark.asyncio
async def test_numbers_api_temp_quotes_hide_internal_providers(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    async def fake_get_all_prices(service, country, state, ignore_balance=False, with_success_rates=True, provider_codes=None):
        calls["args"] = {
            "service": service,
            "country": country,
            "state": state,
            "ignore_balance": ignore_balance,
            "with_success_rates": with_success_rates,
            "provider_codes": tuple(provider_codes or ()),
        }
        return {
            "textverified": {
                "price": 0.44,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "recommended_success_rate": 91,
                "success_attempts": 5,
            },
            "smsman": {
                "price": 0.01,
                "api_service_name": "telegram",
                "available_for_buy": True,
                "success_attempts": 99,
            },
        }

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "get_all_prices", fake_get_all_prices)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=temp&service=telegram&country=1&state=CA")

    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert calls["auth_scope"] == "numbers:quotes"
    assert calls["args"] == {
        "service": "telegram",
        "country": "1",
        "state": "CA",
        "ignore_balance": True,
        "with_success_rates": False,
        "provider_codes": api.TEMP_QUOTE_PROVIDER_CODES,
    }
    assert payload["ok"] is True
    assert payload["mode"] == "temp"
    assert payload["service"]["key"] == "telegram"
    assert len(payload["providers"]) == 1
    assert payload["providers"][0]["provider_id"].startswith("S")
    assert payload["providers"][0]["provider"] != "textverified"
    assert payload["providers"][0]["price_label"] == "$0.44"
    assert payload["providers"][0]["quote_token"]
    assert response.headers["X-RateLimit-Bucket"] == "numbers:quotes"


@pytest.mark.asyncio
async def test_numbers_api_quotes_reject_unsupported_modes(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=123, scopes=(required_scope,))

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=rental&service=telegram&country=1")

    response = await api.quotes(request)
    payload = json.loads(response.text)

    assert response.status == 400
    assert payload["code"] == "unsupported_mode"
    assert response.headers["X-RateLimit-Bucket"] == "numbers:quotes"


@pytest.mark.asyncio
async def test_numbers_api_create_order_requires_api_key(monkeypatch):
    async def fake_require_api_auth(request, required_scope):
        raise web.HTTPUnauthorized(text="missing api key")

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    request = make_mocked_request("POST", "/api/v1/numbers/orders", headers={"Content-Type": "application/json"})
    request._read_bytes = json.dumps({"quote_token": "quote"}).encode("utf-8")

    with pytest.raises(web.HTTPUnauthorized):
        await api.create_order(request)


@pytest.mark.asyncio
async def test_numbers_api_create_order_uses_order_service(monkeypatch):
    calls = {}

    async def fake_require_api_auth(request, required_scope):
        calls["auth_scope"] = required_scope
        return api_auth_context(key_id="key-1", user_id=123, reseller_id=456, scopes=(required_scope,))

    async def fake_create_temp_order_from_quote(**kwargs):
        calls.update(kwargs)
        return {"ok": True, "order": {"id": "order-1"}}

    monkeypatch.setattr(api, "require_api_auth", fake_require_api_auth)
    monkeypatch.setattr(api, "check_api_rate_limit", allow_rate_limit)
    monkeypatch.setattr(api, "create_temp_order_from_quote", fake_create_temp_order_from_quote)
    request = make_mocked_request(
        "POST",
        "/api/v1/numbers/orders",
        headers={"Content-Type": "application/json", "Authorization": "Bearer key", "Idempotency-Key": "idem-1"},
    )
    request._read_bytes = json.dumps({"quote_token": "quote-1", "language": "en"}).encode("utf-8")

    response = await api.create_order(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {"ok": True, "order": {"id": "order-1"}}
    assert response.headers["X-RateLimit-Bucket"] == "numbers:orders:create"
    assert calls == {
        "auth_scope": "numbers:orders:create",
        "user_id": 123,
        "reseller_id": 456,
        "quote_token": "quote-1",
        "idempotency_key": "idem-1",
        "lang": "en",
    }
