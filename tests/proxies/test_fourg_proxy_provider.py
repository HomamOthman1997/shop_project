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

    async def fake_prices(_package_id):
        return [{"days": "1.00", "hours": 0, "price": 0.7}, {"days": 0, "hours": 3, "price": 0.3}]

    async def fake_history_price():
        return 0.25

    monkeypatch.setattr(provider, "_fetch_packages", fake_packages)
    monkeypatch.setattr(provider, "_fetch_parent_proxies", fake_parents)
    monkeypatch.setattr(provider, "_fetch_prices", fake_prices)
    monkeypatch.setattr(provider, "_estimate_history_price", fake_history_price)
    monkeypatch.setattr(provider, "_package_price_overrides", lambda: {})

    offers = await provider.list_offers()
    assert len(offers) == 1
    offer = offers[0]
    assert offer["offer_id"] == "1:2182"
    assert offer["country"] == "UNITED STATES"
    assert offer["city"] == "New York"
    assert offer["carrier"] == "5G AT&T"
    assert "Golden Package" in offer["title"]
    assert offer["price"] == 0.25
    assert offer["period"] == "Rotation 30m"
    labels = {item["label"] for item in offer["raw"]["duration_options"]}
    assert {"1 Day", "3 Hour"} <= labels


@pytest.mark.asyncio
async def test_rent_offer_uses_package_and_parent_ids(monkeypatch):
    provider = FourGProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST" and path == "/proxies":
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
            "protocol": "socks",
            "duration_value": "1",
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
    assert payload["protocol"] == "socks"
    assert payload["duration"] == "1"


@pytest.mark.asyncio
async def test_reconfigure_proxy_updates_existing_account(monkeypatch):
    provider = FourGProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "PUT" and path == "/proxies/551":
            return (
                200,
                {
                    "result": {
                        "id": 551,
                        "host": "5.6.7.8",
                        "port": 7100,
                        "username": "u2",
                        "password": "p2",
                    }
                },
            )
        return 404, {}

    monkeypatch.setattr(provider, "_request", fake_request)

    result = await provider.reconfigure_proxy(
        {"provider_order_id": 551},
        {
            "provider": "4g",
            "protocol": "http",
            "country": "UNITED STATES",
            "city": "New York",
            "raw": {
                "service_provider_id": 17,
                "service_provider_city_id": 33,
                "country_id": 1,
                "city_id": 2,
            },
        },
    )

    assert result["success"] is True
    assert result["endpoint"] == "5.6.7.8:7100"
    assert calls[0][0] == "PUT"
    assert calls[0][1] == "/proxies/551"
    payload = calls[0][2]["payload"]
    assert payload["protocol"] == "http"
    assert payload["service_provider_id"] == 17
    assert payload["service_provider_city_id"] == 33


def test_normalize_carrier_name_variants():
    provider = FourGProxyProvider()
    assert provider._normalize_carrier_name("T-mobile") == "T-Mobile"
    assert provider._normalize_carrier_name("T-MOBILE") == "T-Mobile"
    assert provider._normalize_carrier_name("VERIZON") == "Verizon"
    assert provider._normalize_carrier_name("AT&T internet services") == "AT&T Internet Services"


def test_normalize_duration_options_excludes_blocked_hours():
    provider = FourGProxyProvider()
    options = provider._normalize_duration_options(
        [
            {"days": 0, "hours": 2, "price": 0.26},
            {"days": 0, "hours": 3, "price": 0.32},
            {"days": 0, "hours": 12, "price": 0.47},
            {"days": 1, "hours": 0, "price": 0.73},
        ]
    )
    labels = [item["label"] for item in options]
    assert "2 Hour" not in labels
    assert "12 Hour" not in labels
    assert "3 Hour" in labels
    assert "1 Day" in labels
