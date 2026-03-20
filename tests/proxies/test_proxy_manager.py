import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.proxies import manager


class DummyProvider:
    def __init__(self, offers=None, rent_result=None):
        self._offers = offers or []
        self._rent_result = rent_result or {"success": True, "order_id": "X1"}

    async def list_offers(self):
        return list(self._offers)

    async def rent_offer(self, offer):
        return dict(self._rent_result, offer_id=offer.get("offer_id"))

    async def refresh_proxy(self, order_data, *, with_check=False):
        return {"success": True, "endpoint": "8.8.8.8:1000", "order_id": "R1"}


def test_proxy_registry_limited_to_two_providers():
    assert set(manager.PROXY_PROVIDERS.keys()) == {"9proxy", "4g"}


@pytest.mark.asyncio
async def test_get_proxy_catalog_aggregates_and_sorts(monkeypatch):
    patched = {
        "9proxy": DummyProvider(
            offers=[
                {"offer_id": "2", "country": "US", "state": "NY", "city": "NYC", "price": 5},
            ]
        ),
        "4g": DummyProvider(
            offers=[
                {"offer_id": "1", "country": "TR", "state": "Istanbul", "city": "Istanbul", "price": 2},
            ]
        ),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)

    offers = await manager.get_proxy_catalog()
    assert len(offers) == 2
    assert offers[0]["provider"] == "4g"
    assert offers[1]["provider"] == "9proxy"


@pytest.mark.asyncio
async def test_get_proxy_catalog_applies_markup_and_defaults(monkeypatch):
    patched = {
        "9proxy": DummyProvider(
            offers=[
                {"offer_id": "u1", "title": "Unlimited Proxy", "country": "US", "price": 10.0},
            ]
        ),
        "4g": DummyProvider(offers=[]),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)
    monkeypatch.setattr(manager.settings, "proxy_service_markup_percent", 10.0, raising=False)

    offers = await manager.get_proxy_catalog()
    assert len(offers) == 1
    offer = offers[0]
    assert offer["base_price"] == 10.0
    assert offer["price"] == 11.0
    assert offer["success_rate"] == 100.0
    assert offer["billing_type"] == "fixed"


@pytest.mark.asyncio
async def test_get_proxy_catalog_hides_unpriced_when_enabled(monkeypatch):
    patched = {
        "9proxy": DummyProvider(offers=[{"offer_id": "u1", "country": "US", "price": 0.0}]),
        "4g": DummyProvider(offers=[]),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)
    monkeypatch.setattr(manager.settings, "proxy_hide_unpriced_offers", True, raising=False)

    offers = await manager.get_proxy_catalog()
    assert offers == []


@pytest.mark.asyncio
async def test_get_proxy_catalog_keeps_unpriced_when_disabled(monkeypatch):
    patched = {
        "9proxy": DummyProvider(offers=[{"offer_id": "u1", "country": "US", "price": 0.0}]),
        "4g": DummyProvider(offers=[]),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)
    monkeypatch.setattr(manager.settings, "proxy_hide_unpriced_offers", False, raising=False)

    offers = await manager.get_proxy_catalog()
    assert len(offers) == 1
    assert offers[0]["offer_id"] == "u1"


@pytest.mark.asyncio
async def test_rent_proxy_offer_unknown_provider():
    result = await manager.rent_proxy_offer({"provider": "unknown", "offer_id": "1"})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_rent_proxy_offer_routes_to_provider(monkeypatch):
    patched = {
        "9proxy": DummyProvider(rent_result={"success": True, "order_id": "R-9"}),
        "4g": DummyProvider(rent_result={"success": True, "order_id": "R-4G"}),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)

    result = await manager.rent_proxy_offer({"provider": "9proxy", "offer_id": "abc"})
    assert result["success"] is True
    assert result["order_id"] == "R-9"
    assert result["offer_id"] == "abc"


@pytest.mark.asyncio
async def test_verify_proxy_offer_delivery_gate_disabled(monkeypatch):
    monkeypatch.setattr(manager.settings, "proxy_quality_gate_enabled", False, raising=False)
    res = await manager.verify_proxy_offer_delivery("10.0.0.1:1000")
    assert res["allowed"] is True
