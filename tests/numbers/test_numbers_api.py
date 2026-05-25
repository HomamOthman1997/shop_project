import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services.numbers import api
from services.numbers import api_payloads


def test_register_numbers_api_routes_adds_versioned_endpoints():
    app = web.Application()

    api.register_numbers_api_routes(app)

    routes = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/v1/numbers/health") in routes
    assert ("GET", "/api/v1/numbers/catalog/bootstrap") in routes
    assert ("GET", "/api/v1/numbers/quotes") in routes


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

    monkeypatch.setattr(api, "get_all_prices", fake_get_all_prices)
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=temp&service=telegram&country=1&state=CA")

    response = await api.quotes(request)
    payload = json.loads(response.text)

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


@pytest.mark.asyncio
async def test_numbers_api_quotes_reject_unsupported_modes():
    request = make_mocked_request("GET", "/api/v1/numbers/quotes?mode=rental&service=telegram&country=1")

    with pytest.raises(web.HTTPBadRequest):
        await api.quotes(request)
