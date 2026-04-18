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

    async def reconfigure_proxy(self, order_data, offer):
        return {"success": True, "endpoint": "9.9.9.9:2000", "order_id": "R2"}


class DummyUsernameProvider(DummyProvider):
    def __init__(self, available: set[str]):
        super().__init__()
        self.available = set(available)
        self.checked: list[str] = []

    async def check_username_available(self, username: str):
        self.checked.append(username)
        return username in self.available


def test_proxy_registry_keeps_4g_enabled_while_9proxy_is_suspended():
    assert "4g" in manager.PROXY_PROVIDERS
    assert "9proxy" not in manager.PROXY_PROVIDERS


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
async def test_get_proxy_catalog_numbers_modems_inside_each_carrier(monkeypatch):
    patched = {
        "4g": DummyProvider(
            offers=[
                {
                    "offer_id": "1:302",
                    "country": "US",
                    "city": "NYC",
                    "carrier": "5G T-Mobile",
                    "price": 1.0,
                    "raw": {"parent_proxy_id": 302},
                },
                {
                    "offer_id": "1:301",
                    "country": "US",
                    "city": "NYC",
                    "carrier": "5G T-Mobile",
                    "price": 1.0,
                    "raw": {"parent_proxy_id": 301},
                },
                {
                    "offer_id": "1:401",
                    "country": "US",
                    "city": "NYC",
                    "carrier": "5G Verizon",
                    "price": 1.0,
                    "raw": {"parent_proxy_id": 401},
                },
            ]
        ),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)

    offers = await manager.get_proxy_catalog()
    labels_by_id = {offer["offer_id"]: offer["modem_label"] for offer in offers}

    assert labels_by_id["1:301"] == "5G T-Mobile1"
    assert labels_by_id["1:302"] == "5G T-Mobile2"
    assert labels_by_id["1:401"] == "5G Verizon1"


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


@pytest.mark.asyncio
async def test_reconfigure_proxy_order_routes_to_provider(monkeypatch):
    patched = {
        "4g": DummyProvider(),
    }
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", patched)
    async def _fake_quality(_endpoint):
        return {"allowed": True, "decision": "pass", "reason": "ok"}

    monkeypatch.setattr(manager, "verify_proxy_offer_delivery", _fake_quality)

    result = await manager.reconfigure_proxy_order(
        {"provider": "4g", "provider_order_id": "551", "_id": "oid-1"},
        {"provider": "4g", "offer_id": "1:2182", "country": "US"},
    )
    assert result["success"] is True
    assert result["endpoint"] == "9.9.9.9:2000"


def test_unlimited_category_accepts_only_golden_4g():
    from services.proxies.handlers.proxy_flow import _category_provider_match

    assert _category_provider_match({"provider": "4g", "title": "Golden Package | Verizon 5G | 5G"}, "unlimited") is True
    assert _category_provider_match({"provider": "4g", "title": "Silver Package | Verizon 5G | 5G"}, "unlimited") is False
    assert _category_provider_match({"provider": "4g", "title": "Injection Package | Verizon 5G | 5G"}, "unlimited") is False
    assert _category_provider_match({"provider": "cyberyozh", "raw": {"proxy_category": "residential_static"}}, "unlimited") is True
    assert _category_provider_match({"provider": "cyberyozh", "raw": {"proxy_category": "lte"}}, "unlimited") is False


@pytest.mark.asyncio
async def test_reserve_available_4g_username_uses_short_ph_prefix(monkeypatch):
    provider = DummyUsernameProvider({"PH0315"})
    monkeypatch.setattr(manager, "PROXY_PROVIDERS", {"4g": provider})
    monkeypatch.setattr(manager.secrets, "randbelow", lambda _n: 315)

    username = await manager.reserve_available_4g_username()

    assert username == "PH0315"
    assert provider.checked == ["PH0315"]
