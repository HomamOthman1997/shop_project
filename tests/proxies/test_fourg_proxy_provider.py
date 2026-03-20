import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.proxies.providers.fourg_proxy_provider import FourGProxyProvider


@pytest.mark.asyncio
async def test_list_offers_builds_available_parent_proxy_offer(monkeypatch):
    provider = FourGProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    async def fake_packages():
        return [{"id": 1, "package_name": "Golden Package"}]

    async def fake_parents(_package_id):
        return [
            {
                "id": 2182,
                "country_name": "UNITED STATES",
                "city_name": "New York",
                "service_provider_name": "5G AT&T",
                "technology": "5G",
                "rotation_time": 30,
                "is_available": True,
                "status": "ACTIVE",
            },
            {
                "id": 9999,
                "country_name": "UNITED STATES",
                "city_name": "Los Angeles",
                "is_available": False,
                "status": "ACTIVE",
            },
        ]

    async def fake_history_price():
        return 0.25

    monkeypatch.setattr(provider, "_fetch_packages", fake_packages)
    monkeypatch.setattr(provider, "_fetch_parent_proxies", fake_parents)
    monkeypatch.setattr(provider, "_estimate_history_price", fake_history_price)
    monkeypatch.setattr(provider, "_package_price_overrides", lambda: {})

    offers = await provider.list_offers()
    assert len(offers) == 1
    offer = offers[0]
    assert offer["offer_id"] == "1:2182"
    assert offer["country"] == "UNITED STATES"
    assert offer["city"] == "New York"
    assert "Golden Package" in offer["title"]
    assert offer["price"] == 0.25


@pytest.mark.asyncio
async def test_rent_offer_uses_package_and_parent_ids(monkeypatch):
    provider = FourGProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST" and path == "/api/v2/proxy-accounts":
            return (
                200,
                {
                    "result": {
                        "id": 551,
                        "host": "1.2.3.4",
                        "port": 7000,
                        "username": "u1",
                        "password": "p1",
                    }
                },
            )
        return 404, {}

    monkeypatch.setattr(provider, "_request", fake_request)

    result = await provider.rent_offer(
        {
            "offer_id": "1:2182",
            "country": "UNITED STATES",
            "city": "New York",
            "raw": {"package_id": 1, "parent_proxy_id": 2182},
        }
    )

    assert result["success"] is True
    assert result["endpoint"] == "1.2.3.4:7000"
    assert calls
    payload = calls[0][2]["payload"]
    assert payload["package_id"] == 1
    assert payload["pkg_id"] == 1
    assert payload["parent_proxy_id"] == 2182
