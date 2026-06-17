import os
import sys

import pytest

sys.path.insert(0, os.getcwd())

from services.digital_products import esim_web

OFFER = {
    "price_usd": 5.0,
    "_cost_price_usd": 3.0,
    "parts": [{"country": "Spain", "plan": {"package_code": "ES7", "price_usd": 3.0, "_cost_price_usd": 3.0, "data_type_code": 2}}],
}


class _FakeFM:
    @staticmethod
    async def process_core_purchase(**_kwargs):
        return True, None

    @staticmethod
    async def refund_core_purchase(**_kwargs):
        return True, None


def _patch_common(monkeypatch, *, calls):
    monkeypatch.setattr(esim_web, "esim_provider_configured", lambda: True)

    async def create_order(**_kwargs):
        return {"_id": "ord-1"}

    async def update_status(order_id, status):
        calls.setdefault("status", []).append(status)

    async def update_details(order_id, patch):
        calls.setdefault("details", []).append(patch)

    async def notify(*_args, **_kwargs):
        calls.setdefault("notified", 0)
        calls["notified"] += 1

    monkeypatch.setattr(esim_web, "create_order_v3", create_order)
    monkeypatch.setattr(esim_web, "update_order_status", update_status)
    monkeypatch.setattr(esim_web, "update_order_details", update_details)
    monkeypatch.setattr(esim_web, "notify_customer", notify)
    monkeypatch.setattr(esim_web, "FinancialManager", _FakeFM)


@pytest.mark.asyncio
async def test_purchase_rejected_when_provider_not_configured(monkeypatch):
    monkeypatch.setattr(esim_web, "esim_provider_configured", lambda: False)
    result = await esim_web.purchase_esim_offer(user_id=1, reseller_id=1, offer=OFFER, days=7)
    assert result["ok"] is False
    assert result["code"] == "esim_not_configured"


@pytest.mark.asyncio
async def test_purchase_delivers_profiles(monkeypatch):
    calls: dict = {}
    _patch_common(monkeypatch, calls=calls)

    class FakeClient:
        async def order_profiles(self, **_kwargs):
            return {"success": True, "obj": {"orderNo": "NO1"}}

        async def query_profiles(self, **_kwargs):
            return {"success": True, "obj": {"esimList": [{"iccid": "123", "qrCodeUrl": "http://q", "ac": "AC1"}]}}

    monkeypatch.setattr(esim_web, "EsimAccessClient", FakeClient)
    result = await esim_web.purchase_esim_offer(user_id=1, reseller_id=1, offer=OFFER, days=7)

    assert result["ok"] is True
    assert result["status"] == "delivered"
    assert result["profiles"][0] == {"iccid": "123", "qr": "http://q", "ac": "AC1"}
    assert "success" in calls["status"]


@pytest.mark.asyncio
async def test_purchase_refunds_on_provider_failure(monkeypatch):
    calls: dict = {}
    refunded = {}
    _patch_common(monkeypatch, calls=calls)

    class FakeFMRefund(_FakeFM):
        @staticmethod
        async def refund_core_purchase(**_kwargs):
            refunded["yes"] = True
            return True, None

    monkeypatch.setattr(esim_web, "FinancialManager", FakeFMRefund)

    class FakeClient:
        async def order_profiles(self, **_kwargs):
            return {"success": False, "errorMessage": "provider down"}

        async def query_profiles(self, **_kwargs):
            return {"success": False}

    monkeypatch.setattr(esim_web, "EsimAccessClient", FakeClient)
    result = await esim_web.purchase_esim_offer(user_id=1, reseller_id=1, offer=OFFER, days=7)

    assert result["ok"] is False
    assert result["code"] == "provider_failed"
    assert refunded.get("yes") is True
    assert "refunded" in calls["status"]


@pytest.mark.asyncio
async def test_purchase_preparing_when_profile_not_ready(monkeypatch):
    calls: dict = {}
    _patch_common(monkeypatch, calls=calls)

    class FakeClient:
        async def order_profiles(self, **_kwargs):
            return {"success": True, "obj": {"orderNo": "NO1"}}

        async def query_profiles(self, **_kwargs):
            return {"success": True, "obj": {"esimList": []}}

    monkeypatch.setattr(esim_web, "EsimAccessClient", FakeClient)
    result = await esim_web.purchase_esim_offer(user_id=1, reseller_id=1, offer=OFFER, days=7)

    assert result["ok"] is True
    assert result["status"] == "preparing"
    assert "paid" in calls["status"]
