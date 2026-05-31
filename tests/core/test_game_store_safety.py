import os
import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from handlers.store_sections import (
    _apply_markup_decimal,
    _notify_owner_pending_game_topup,
    _poll_g2bulk_order_status,
    _provider_status_is_failure,
    _provider_status_is_success,
)


def test_apply_markup_decimal_preserves_live_cent_price():
    assert _apply_markup_decimal("10", "2") == Decimal("10.20")
    assert _apply_markup_decimal("0.87", "2") == Decimal("0.89")
    assert _apply_markup_decimal("15.37", "0") == Decimal("15.37")


def test_provider_status_helpers_are_conservative():
    assert _provider_status_is_success({"data": {"status": "completed"}}) is True
    assert _provider_status_is_failure({"data": {"status": "failed"}}) is True
    assert _provider_status_is_success({"data": {"status": "processing"}}) is False
    assert _provider_status_is_failure({"data": {"status": "processing"}}) is False


@pytest.mark.asyncio
async def test_poll_g2bulk_order_status_waits_for_final_success():
    class FakeClient:
        def __init__(self):
            self.responses = [
                {"status": 200, "data": {"status": "processing"}},
                {"status": 200, "data": {"status": "pending"}},
                {"status": 200, "data": {"status": "completed"}},
            ]

        async def get_order_status(self, _order_id):
            return self.responses.pop(0)

    resp = await _poll_g2bulk_order_status(FakeClient(), "123", attempts=3, delay_sec=0)
    assert resp == {"status": 200, "data": {"status": "completed"}}


@pytest.mark.asyncio
async def test_poll_g2bulk_order_status_stops_on_failure():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get_order_status(self, _order_id):
            self.calls += 1
            if self.calls == 1:
                return {"status": 200, "data": {"status": "pending"}}
            return {"status": 200, "data": {"status": "failed"}}

    client = FakeClient()
    resp = await _poll_g2bulk_order_status(client, "123", attempts=5, delay_sec=0)
    assert resp == {"status": 200, "data": {"status": "failed"}}
    assert client.calls == 2


@pytest.mark.asyncio
async def test_pending_game_topup_notifies_manual_fulfillment(monkeypatch):
    import handlers.store_sections as store_sections

    calls = {}

    async def fake_update_order_details(order_id, payload):
        calls["details"] = {"order_id": order_id, "payload": payload}

    async def fake_notify(**kwargs):
        calls["notify"] = kwargs
        return True

    monkeypatch.setattr(store_sections, "update_order_details", fake_update_order_details)
    monkeypatch.setattr(store_sections, "_notify_owner_manual_topup", fake_notify)

    order = {"_id": "order-1", "user_id": 123, "reseller_id": 456}
    await _notify_owner_pending_game_topup(
        bot=object(),
        order=order,
        item_name="1800 Uc Voucher",
        provider_code="g2bulk",
        external_order_id="ext-1",
        game_name="Pubg",
        player_id="5275962503",
        server_id="",
        reason="Provider confirmation stayed pending after automatic polling.",
    )

    assert calls["details"]["order_id"] == "order-1"
    assert calls["details"]["payload"]["fulfillment_mode"] == store_sections.MANUAL_TOPUP_MODE
    assert calls["details"]["payload"]["manual_fulfillment_status"] == "pending"
    assert calls["details"]["payload"]["provider_manual_review_required"] is True
    assert calls["notify"]["order"] == order
    assert calls["notify"]["item_name"] == "1800 Uc Voucher"
    assert calls["notify"]["external_order_id"] == "ext-1"
    assert calls["notify"]["player_data"]["player_id"] == "5275962503"


@pytest.mark.asyncio
async def test_recover_manual_digital_order_sends_owner_notification(monkeypatch):
    import handlers.store_sections as store_sections

    calls = {}
    order = {
        "_id": "order-1",
        "service_type": "core_digital_products",
        "status": "paid",
        "provider_code": "g2bulk",
        "provider_order_id": "provider-1",
        "game_id": "pubgm",
        "player_id": "5275962503",
        "server_id": "",
    }

    async def fake_find_order(order_id):
        calls["find"] = order_id
        return order

    async def fake_snapshot(force=False):
        return {"games": [{"id": "pubgm", "name": "Pubg"}]}

    async def fake_notify(**kwargs):
        calls["notify"] = kwargs
        return True

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_find_order_for_owner_action", fake_find_order)
    monkeypatch.setattr(store_sections, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(store_sections, "_notify_owner_pending_game_topup", fake_notify)

    answers = []

    class FakeMessage:
        text = "/recover_digital_order order-1 1800 UC Voucher"
        from_user = SimpleNamespace(id=7417429062)
        bot = object()

        async def answer(self, text, **_kwargs):
            answers.append(text)

    await store_sections.recover_manual_digital_order(FakeMessage())

    assert calls["find"] == "order-1"
    assert calls["notify"]["order"] == order
    assert calls["notify"]["item_name"] == "1800 UC Voucher"
    assert calls["notify"]["external_order_id"] == "provider-1"
    assert calls["notify"]["player_id"] == "5275962503"
    assert "Recovery notification sent" in answers[-1]
