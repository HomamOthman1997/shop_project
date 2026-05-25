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
