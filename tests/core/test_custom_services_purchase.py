import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())

import handlers.custom_services as custom_services


class _FakeState:
    def __init__(self, data):
        self._data = dict(data)
        self.cleared = False
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self.cleared = True

    async def set_state(self, value):
        self.state = value


class _FakeMessage:
    def __init__(self):
        self.answers = []
        self.edits = []
        self.bot = SimpleNamespace()
        self.from_user = SimpleNamespace(id=77)

    async def answer(self, text, **kwargs):
        self.answers.append({"text": str(text), "kwargs": kwargs})
        return SimpleNamespace(message_id=1)

    async def edit_text(self, text, **kwargs):
        self.edits.append({"text": str(text), "kwargs": kwargs})
        return SimpleNamespace(message_id=1)


@pytest.mark.asyncio
async def test_execute_buy_blocks_unconfigured_endpoint(monkeypatch):
    state = _FakeState(
        {
            "buy_endpoint_id": "ep1",
            "buy_catalog_owner_id": 500,
            "buy_wallet_scope_id": 500,
            "buy_catalog_type": "custom",
            "buy_pending_qty": 1,
            "buy_min_qty": 1,
        }
    )
    message = _FakeMessage()

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep1",
            "node_type": "endpoint",
            "reseller_id": 500,
            "delivery_type": "",
            "available_qty": 5,
        }

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)

    await custom_services._execute_buy(message, state, 77)

    assert state.cleared is True
    assert any("not ready for sale" in row["text"].lower() for row in message.answers)


@pytest.mark.asyncio
async def test_execute_buy_uses_reserve_for_text_delivery(monkeypatch):
    state = _FakeState(
        {
            "buy_endpoint_id": "ep2",
            "buy_catalog_owner_id": 500,
            "buy_wallet_scope_id": 500,
            "buy_catalog_type": "custom",
            "buy_pending_qty": 2,
            "buy_min_qty": 1,
            "buy_unit_price": 3.5,
            "buy_service_name": "Mailer",
            "buy_financial_mode": "custom",
            "buy_return_node_id": "folder1",
        }
    )
    message = _FakeMessage()
    reserve_calls = []
    claim_calls = []
    delivery_calls = []

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep2",
            "node_type": "endpoint",
            "reseller_id": 500,
            "delivery_type": "text",
            "delivery_text": "payload",
            "available_qty": 5,
            "price": 3.5,
            "name": "Mailer",
        }

    async def _fake_reserve(_node_id, _owner_id, qty, **_kwargs):
        reserve_calls.append(qty)
        return {"available_qty": 3}

    async def _fake_claim(*_args, **_kwargs):
        claim_calls.append(True)
        return None

    async def _fake_create_order_v3(**_kwargs):
        return {"_id": "order1"}

    async def _fake_process_custom_purchase(*_args, **_kwargs):
        return True, "ok"

    async def _fake_update_order_details(*_args, **_kwargs):
        return None

    async def _fake_update_order_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "reserve_endpoint_stock", _fake_reserve)
    monkeypatch.setattr(custom_services, "claim_endpoint_inventory", _fake_claim)
    monkeypatch.setattr(custom_services, "create_order_v3", _fake_create_order_v3)
    monkeypatch.setattr(custom_services.FinancialManager, "process_custom_purchase", _fake_process_custom_purchase)
    monkeypatch.setattr(custom_services, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(custom_services, "update_order_status", _fake_update_order_status)

    await custom_services._execute_buy(message, state, 77, result_message=message)

    assert reserve_calls == [2]
    assert claim_calls == []
    assert delivery_calls == []
    assert message.edits
    assert "Purchase Completed" in message.edits[-1]["text"]
    assert "payload" in message.edits[-1]["text"]


@pytest.mark.asyncio
async def test_execute_buy_creates_preorder_when_enabled(monkeypatch):
    state = _FakeState(
        {
            "buy_endpoint_id": "ep3",
            "buy_catalog_owner_id": 500,
            "buy_wallet_scope_id": 500,
            "buy_catalog_type": "custom",
            "buy_pending_qty": 1,
            "buy_min_qty": 1,
            "buy_unit_price": 4.0,
            "buy_service_name": "PayPal Accounts",
            "buy_financial_mode": "custom",
            "buy_return_node_id": "folder1",
            "buy_is_preorder": True,
            "buy_customer_note": "Need Gmail for US profile",
        }
    )
    message = _FakeMessage()
    created = {}
    notified = []

    async def _fake_get_user(_user_id):
        return {"language": "en", "username": "buyer1"}

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep3",
            "node_type": "endpoint",
            "reseller_id": 500,
            "delivery_type": "inventory",
            "available_qty": 0,
            "price": 4.0,
            "name": "PayPal Accounts",
            "preorder_enabled": True,
        }

    async def _fake_create_order_v3(**_kwargs):
        return {"_id": "order3"}

    async def _fake_process_custom_purchase(*_args, **_kwargs):
        return True, "ok"

    async def _fake_create_preorder_request(**kwargs):
        created.update(kwargs)
        return {"_id": "pre1", **kwargs}

    async def _fake_update_order_details(*_args, **_kwargs):
        return None

    async def _fake_update_order_status(*_args, **_kwargs):
        return None

    async def _fake_notify_owner_preorder_created(**kwargs):
        notified.append(kwargs)

    async def _fake_get_pending_preorder_position(_preorder_id):
        return 1

    async def _fake_can_use_preorder(_endpoint, _bot):
        return True

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "create_order_v3", _fake_create_order_v3)
    monkeypatch.setattr(custom_services.FinancialManager, "process_custom_purchase", _fake_process_custom_purchase)
    monkeypatch.setattr(custom_services, "create_preorder_request", _fake_create_preorder_request)
    monkeypatch.setattr(custom_services, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(custom_services, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(custom_services, "_notify_owner_preorder_created", _fake_notify_owner_preorder_created)
    monkeypatch.setattr(custom_services, "get_pending_preorder_position", _fake_get_pending_preorder_position)
    monkeypatch.setattr(custom_services, "_can_use_preorder", _fake_can_use_preorder)

    await custom_services._execute_buy(message, state, 77)

    assert created["buyer_user_id"] == 77
    assert created["service_name"] == "PayPal Accounts"
    assert created["customer_note"] == "Need Gmail for US profile"
    assert notified
    assert any("Reservation created successfully" in row["text"] for row in message.answers)


@pytest.mark.asyncio
async def test_fulfill_custom_preorder_completes_order_and_notifies(monkeypatch):
    calls = {"details": [], "statuses": [], "notified": []}
    preorder = {
        "_id": "pre1",
        "endpoint_id": "ep3",
        "catalog_owner_id": 500,
        "catalog_type": "custom",
        "buyer_user_id": 77,
        "order_id": "order3",
        "qty": 1,
        "status": "pending",
    }

    class _Message:
        text = "Custom Service Preorder"

        async def edit_text(self, text, **kwargs):
            self.text = text

    class _Callback:
        data = "custom_preorder:fulfill:pre1"
        from_user = SimpleNamespace(id=9001)
        bot = SimpleNamespace()
        message = _Message()

        def __init__(self):
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    async def _fake_get_preorder(_preorder_id):
        return dict(preorder)

    async def _fake_next_pending(_endpoint_id):
        return dict(preorder)

    async def _fake_mark_fulfilling(_preorder_id, actor_id):
        return {**preorder, "status": "fulfilling"}

    async def _fake_mark_fulfilled(_preorder_id, actor_id):
        return {**preorder, "status": "fulfilled"}

    async def _fake_get_node(*_args, **_kwargs):
        return {"_id": "ep3", "name": "PayPal Accounts"}

    async def _fake_update_order_details(order_id, payload):
        calls["details"].append((order_id, payload))

    async def _fake_update_order_status(order_id, status):
        calls["statuses"].append((order_id, status))

    async def _fake_notify(**kwargs):
        calls["notified"].append(kwargs)
        return True

    monkeypatch.setattr(custom_services, "OWNER_ID", 9001)
    monkeypatch.setattr(custom_services, "get_preorder_request", _fake_get_preorder)
    monkeypatch.setattr(custom_services, "get_next_pending_preorder", _fake_next_pending)
    monkeypatch.setattr(custom_services, "mark_preorder_fulfilling", _fake_mark_fulfilling)
    monkeypatch.setattr(custom_services, "mark_preorder_fulfilled", _fake_mark_fulfilled)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(custom_services, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(custom_services, "_notify_preorder_completed_user", _fake_notify)

    callback = _Callback()
    await custom_services.fulfill_custom_preorder(callback)

    assert calls["statuses"] == [("order3", "success")]
    assert calls["details"][0][1]["custom_preorder_fulfilled_manually"] is True
    assert calls["notified"]
    assert callback.answers[-1]["text"] == "Preorder fulfilled"
