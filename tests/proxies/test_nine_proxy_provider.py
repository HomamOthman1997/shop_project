import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.proxies.providers.nine_proxy_provider import NineProxyProvider


@pytest.mark.asyncio
async def test_list_offers_uses_balance_data(monkeypatch):
    provider = NineProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    async def fake_request(method, path, **kwargs):
        if method == "GET" and path == "/client/v1/account/get-balance-data":
            return (
                200,
                {
                    "success": True,
                    "result": {
                        "ip_plan_data": {"number_of_ips": 120, "price_per_ip": 0.95},
                        "traffic_plan_data": {"amount_traffic": 3_000_000_000, "price_per_gb": 0.45},
                    },
                },
            )
        return 404, {}

    monkeypatch.setattr(provider, "_request", fake_request)

    offers = await provider.list_offers()
    assert len(offers) == 2
    assert offers[0]["offer_id"] == "unlimited_proxy"
    assert offers[0]["title"] == "Unlimited Proxy"
    assert offers[0]["price"] == 0.95
    assert "IP available" in offers[0]["period"]

    assert offers[1]["offer_id"] == "traffic_proxy_gb"
    assert offers[1]["title"] == "Consumable Proxy (GB)"
    assert offers[1]["price"] == 0.45
    assert "GB available" in offers[1]["period"]


@pytest.mark.asyncio
async def test_rent_offer_uses_client_v1_proxy_connection_create(monkeypatch):
    provider = NineProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST" and path == "/client/v1/proxy-connection/create":
            return (
                200,
                {
                    "success": True,
                    "result": {
                        "id": 77,
                        "host": "1.2.3.4",
                        "port": 31000,
                        "user_name": "u1",
                        "use_key": "p1",
                    },
                },
            )
        return 404, {}

    monkeypatch.setattr(provider, "_request", fake_request)

    result = await provider.rent_offer(
        {
            "provider": "9proxy",
            "offer_id": "unlimited_proxy",
            "title": "Unlimited Proxy",
            "country": "Any",
            "state": "Any",
            "city": "Any",
            "price": 1.0,
            "raw": {"api_model": "client_v1_plan", "product_type": "unlimited_proxy"},
        }
    )
    assert calls
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/client/v1/proxy-connection/create"
    assert result["success"] is True
    assert result["endpoint"] == "1.2.3.4:31000"
    assert result["username"] == "u1"
    assert result["password"] == "p1"
