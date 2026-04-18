import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.proxies.providers.cyberyozh_proxy_provider import CyberYozhProxyProvider


@pytest.mark.asyncio
async def test_cyberyozh_list_offers_maps_static_products(monkeypatch):
    provider = CyberYozhProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    responses = [
        (
            200,
            {
                "results": [
                    {
                        "access_type": "private",
                        "proxy_products": [
                            {
                                "id": "offer-1",
                                "title": "US AT&T",
                                "location_country_code": "US",
                                "price_usd": "5.39",
                                "days": 30,
                                "proxy_category": "residential_static",
                                "stock_status": "in_stock",
                                "traffic_limitation": -1,
                                "is_auto_renewal_possible": True,
                            },
                            {
                                "id": "offer-2",
                                "title": "US Out",
                                "location_country_code": "US",
                                "price_usd": "4.20",
                                "days": 30,
                                "proxy_category": "residential_static",
                                "stock_status": "out_of_stock",
                            },
                        ],
                    }
                ],
                "next": None,
                "nextPage": None,
            },
        )
    ]

    async def _fake_request(method, path, *, params=None, payload=None):
        assert method == "GET"
        assert path == "/proxies/shop/"
        return responses.pop(0)

    monkeypatch.setattr(provider, "_request", _fake_request)

    offers = await provider.list_offers()

    assert len(offers) == 1
    offer = offers[0]
    assert offer["provider"] == "cyberyozh"
    assert offer["country"] == "United States"
    assert offer["state"] == "Any"
    assert offer["carrier"] == "CyberYozh Static"
    assert offer["period"] == "Static"
    assert offer["price"] == 5.39
    assert offer["raw"]["protocol_options"] == ["http", "socks"]
    assert offer["raw"]["duration_options"][0]["value"] == "30"
    assert offer["raw"]["button_label"] == "US AT&T"


@pytest.mark.asyncio
async def test_cyberyozh_rent_offer_uses_list_payload_and_new_credentials(monkeypatch):
    provider = CyberYozhProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    snapshots = [
        {"1.1.1.1:1000:user1:pass1"},
        {
            "1.1.1.1:1000:user1:pass1",
            "2.2.2.2:2000:user2:pass2",
        },
    ]

    async def _fake_snapshot(protocol):
        assert protocol == "socks"
        return snapshots.pop(0)

    captured = {}

    async def _fake_request(method, path, *, params=None, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return 201, [{"id": "proxy-order-1"}]

    monkeypatch.setattr(provider, "_fetch_credentials_snapshot", _fake_snapshot)
    monkeypatch.setattr(provider, "_request", _fake_request)

    result = await provider.rent_offer(
        {
            "offer_id": "offer-1",
            "protocol": "socks",
            "raw": {"days": 30},
        }
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/proxies/shop/buy_proxies/"
    assert captured["payload"] == [{"id": "offer-1", "auto_renew": False}]
    assert result["success"] is True
    assert result["order_id"] == "proxy-order-1"
    assert result["endpoint"] == "2.2.2.2:2000"
    assert result["username"] == "user2"
    assert result["password"] == "pass2"
    assert result["expires_at"] == "30d"


@pytest.mark.asyncio
async def test_cyberyozh_rent_offer_fails_when_credentials_missing(monkeypatch):
    provider = CyberYozhProxyProvider()
    monkeypatch.setattr(provider, "_configured", lambda: True)

    async def _fake_snapshot(_protocol):
        return set()

    async def _fake_request(method, path, *, params=None, payload=None):
        return 201, [{"id": "proxy-order-1"}]

    monkeypatch.setattr(provider, "_fetch_credentials_snapshot", _fake_snapshot)
    monkeypatch.setattr(provider, "_request", _fake_request)

    result = await provider.rent_offer({"offer_id": "offer-1", "protocol": "http", "raw": {"days": 30}})

    assert result["success"] is False
    assert result["raw"]["title"] == "CREDENTIALS_NOT_READY"
