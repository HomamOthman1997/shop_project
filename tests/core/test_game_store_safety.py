import os
import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

from handlers.store_sections import (
    _apply_markup_decimal,
    _extract_voucher_lines,
    _notify_owner_pending_game_topup,
    _notify_owner_manual_topup,
    _owner_notification_routes,
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
    assert _provider_status_is_success({"data": {"order": {"status": "COMPLETED"}}}) is True
    assert _provider_status_is_failure({"data": {"status": "failed"}}) is True
    assert _provider_status_is_success({"data": {"status": "processing"}}) is False
    assert _provider_status_is_failure({"data": {"status": "processing"}}) is False


def test_extract_voucher_lines_reads_g2bulk_delivery_response():
    assert _extract_voucher_lines(
        {
            "status": 200,
            "data": {"order": {"status": "COMPLETED"}},
            "delivery_response": {
                "status": 200,
                "data": {"delivery_items": ["ZJRBuUUf232b37Fdc2"]},
            },
        }
    ) == ["ZJRBuUUf232b37Fdc2"]


def test_owner_notification_routes_adds_owner_dm_fallback(monkeypatch):
    import handlers.store_sections as store_sections

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    assert _owner_notification_routes(-100123, 55) == [
        (-100123, 55, "owner_notifications"),
        (7417429062, None, "owner_dm_fallback"),
    ]


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

        async def get_order_delivery(self, _order_id):
            return {"status": 200, "data": {"delivery_items": ["CODE-1"]}}

    resp = await _poll_g2bulk_order_status(FakeClient(), "123", attempts=3, delay_sec=0)
    assert resp["status"] == 200
    assert resp["data"] == {"status": "completed"}
    assert resp["delivery_response"] == {"status": 200, "data": {"delivery_items": ["CODE-1"]}}


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

        async def get_order_delivery(self, _order_id):
            return {"status": 200, "data": {"delivery_items": ["CODE-1"]}}

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
async def test_manual_topup_notification_falls_back_to_owner_dm(monkeypatch):
    import handlers.store_sections as store_sections

    async def fake_target():
        return -100123, 55

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_owner_notification_target", fake_target)

    calls = []

    class FakeBot:
        async def send_message(self, **kwargs):
            calls.append(kwargs)
            if kwargs["chat_id"] == -100123:
                raise RuntimeError("missing channel access")
            return SimpleNamespace(message_id=10)

    sent = await _notify_owner_manual_topup(
        bot=FakeBot(),
        order={"_id": "order-1", "user_id": 123, "reseller_id": 456},
        item_name="1800 UC Voucher",
        provider_code="g2bulk",
        external_order_id="252882",
        player_data={"player_id": "5275962503"},
        delivery_lines=["CODE-1"],
    )

    assert sent is True
    assert calls[0]["chat_id"] == -100123
    assert calls[0]["message_thread_id"] == 55
    assert calls[1]["chat_id"] == 7417429062
    assert "CODE-1" in calls[1]["text"]


@pytest.mark.asyncio
async def test_claim_manual_topup_notifies_customer_processing(monkeypatch):
    import handlers.store_sections as store_sections

    calls: dict[str, object] = {}
    order = {
        "_id": "order-1",
        "user_id": 123,
        "reseller_id": 123,
        "status": "paid",
        "fulfillment_mode": store_sections.MANUAL_TOPUP_MODE,
        "manual_item_name": "1800 UC",
    }

    async def fake_find(_order_id):
        return order

    async def fake_update(order_id, payload):
        calls["update"] = (order_id, payload)

    async def fake_get_user(_user_id):
        return {"language": "en"}

    class FakeBot:
        async def send_message(self, **kwargs):
            calls["send"] = kwargs

    class FakeMessage:
        text = "Manual digital top-up pending"

        async def edit_text(self, text):
            calls["edit"] = text

    class FakeCallback:
        from_user = SimpleNamespace(id=7417429062)
        data = "dpm:claim:order-1"
        bot = FakeBot()
        message = FakeMessage()

        async def answer(self, text=None, show_alert=None):
            calls["answer"] = (text, show_alert)

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_find_order_for_owner_action", fake_find)
    monkeypatch.setattr(store_sections, "update_order_details", fake_update)
    monkeypatch.setattr(store_sections, "get_user", fake_get_user)

    await store_sections.claim_manual_digital_topup(FakeCallback())

    assert calls["update"][1]["manual_fulfillment_status"] == "processing"
    assert calls["send"]["chat_id"] == 123
    assert "now processing" in calls["send"]["text"]
    assert calls["answer"] == ("Claimed", None)


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

    async def fake_poll(**_kwargs):
        return {"status": 200, "data": {"order": {"status": "processing"}}}

    async def fake_update_details(*_args, **_kwargs):
        return None

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_find_order_for_owner_action", fake_find_order)
    monkeypatch.setattr(store_sections, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(store_sections, "_poll_provider_order_status", fake_poll)
    monkeypatch.setattr(store_sections, "update_order_details", fake_update_details)
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


@pytest.mark.asyncio
async def test_recover_manual_digital_order_marks_completed_provider_order(monkeypatch):
    import handlers.store_sections as store_sections

    calls = {}
    order = {
        "_id": "order-2",
        "service_type": "core_digital_products",
        "status": "paid",
        "provider_code": "g2bulk",
        "provider_order_id": "252882",
        "game_id": "pubgm",
        "player_id": "5275962503",
        "server_id": "",
        "retail_amount": 21.63,
        "user_id": 123,
    }

    async def fake_find_order(_order_id):
        return order

    async def fake_snapshot(force=False):
        return {"games": [{"id": "pubgm", "name": "Pubg"}]}

    async def fake_poll(**_kwargs):
        return {"status": 200, "data": {"order": {"status": "COMPLETED"}}}

    async def fake_update_status(oid, status):
        calls["status"] = (oid, status)

    async def fake_update_details(oid, payload):
        calls.setdefault("details", []).append((oid, dict(payload)))

    async def fake_get_user(_user_id):
        return {"language": "en"}

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_find_order_for_owner_action", fake_find_order)
    monkeypatch.setattr(store_sections, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(store_sections, "_poll_provider_order_status", fake_poll)
    monkeypatch.setattr(store_sections, "update_order_status", fake_update_status)
    monkeypatch.setattr(store_sections, "update_order_details", fake_update_details)
    monkeypatch.setattr(store_sections, "get_user", fake_get_user)

    answers = []
    sent_messages = []

    class FakeBot:
        async def send_message(self, **kwargs):
            sent_messages.append(kwargs)

    class FakeMessage:
        text = "/recover_digital_order order-2 1800 UC Voucher"
        from_user = SimpleNamespace(id=7417429062)
        bot = FakeBot()

        async def answer(self, text, **_kwargs):
            answers.append(text)

    await store_sections.recover_manual_digital_order(FakeMessage())

    assert calls["status"] == ("order-2", "success")
    assert any(call[1].get("provider_recovery_outcome") == "success" for call in calls["details"])
    assert "Provider order is already completed" in answers[-1]
    assert sent_messages


@pytest.mark.asyncio
async def test_resend_digital_delivery_allows_already_success_order(monkeypatch):
    import handlers.store_sections as store_sections

    order = {
        "_id": "order-3",
        "service_type": "core_digital_products",
        "status": "success",
        "provider_code": "g2bulk",
        "provider_order_id": "252882",
        "game_id": "pubgm",
        "player_id": "5275962503",
        "server_id": "",
        "retail_amount": 21.63,
        "user_id": 123,
    }

    async def fake_find_order(_order_id):
        return order

    async def fake_snapshot(force=False):
        return {"games": [{"id": "pubgm", "name": "Pubg"}]}

    async def fake_poll(**_kwargs):
        return {
            "status": 200,
            "data": {"order": {"status": "COMPLETED"}},
            "delivery_response": {"status": 200, "data": {"delivery_items": ["CODE-1"]}},
        }

    async def fake_noop(*_args, **_kwargs):
        return None

    async def fake_get_user(_user_id):
        return {"language": "en"}

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_find_order_for_owner_action", fake_find_order)
    monkeypatch.setattr(store_sections, "get_catalog_snapshot", fake_snapshot)
    monkeypatch.setattr(store_sections, "_poll_provider_order_status", fake_poll)
    monkeypatch.setattr(store_sections, "update_order_status", fake_noop)
    monkeypatch.setattr(store_sections, "update_order_details", fake_noop)
    monkeypatch.setattr(store_sections, "get_user", fake_get_user)

    answers = []
    sent_messages = []

    class FakeBot:
        async def send_message(self, **kwargs):
            sent_messages.append(kwargs)

    class FakeMessage:
        text = "/resend_digital_delivery order-3"
        from_user = SimpleNamespace(id=7417429062)
        bot = FakeBot()

        async def answer(self, text, **_kwargs):
            answers.append(text)

    await store_sections.recover_manual_digital_order(FakeMessage())

    assert "Provider order is already completed" in answers[-1]
    assert "CODE-1" in sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_check_g2bulk_order_reports_delivery_lines(monkeypatch):
    import handlers.store_sections as store_sections

    async def fake_poll(**kwargs):
        assert kwargs["provider"] == "g2bulk"
        assert kwargs["external_order_id"] == "252882"
        return {
            "status": 200,
            "data": {"order": {"status": "COMPLETED"}},
            "delivery_response": {"status": 200, "data": {"delivery_items": ["CODE-1"]}},
        }

    monkeypatch.setattr(store_sections.settings, "owner_id", 7417429062, raising=False)
    monkeypatch.setattr(store_sections, "_poll_provider_order_status", fake_poll)

    answers = []

    class FakeMessage:
        text = "/check_g2bulk_order 252882"
        from_user = SimpleNamespace(id=7417429062)

        async def answer(self, text, **_kwargs):
            answers.append(text)

    await store_sections.check_g2bulk_order(FakeMessage())

    assert "Provider status: completed" in answers[-1]
    assert "Delivery items: 1" in answers[-1]
    assert "CODE-1" in answers[-1]
