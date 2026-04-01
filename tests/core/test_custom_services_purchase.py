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
        self.bot = SimpleNamespace()
        self.from_user = SimpleNamespace(id=77)

    async def answer(self, text, **kwargs):
        self.answers.append({"text": str(text), "kwargs": kwargs})
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

    async def _fake_send_endpoint_delivery(**kwargs):
        delivery_calls.append(kwargs)
        return True

    async def _fake_render_node(*_args, **_kwargs):
        return None

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "reserve_endpoint_stock", _fake_reserve)
    monkeypatch.setattr(custom_services, "claim_endpoint_inventory", _fake_claim)
    monkeypatch.setattr(custom_services, "create_order_v3", _fake_create_order_v3)
    monkeypatch.setattr(custom_services.FinancialManager, "process_custom_purchase", _fake_process_custom_purchase)
    monkeypatch.setattr(custom_services, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(custom_services, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(custom_services, "_send_endpoint_delivery", _fake_send_endpoint_delivery)
    monkeypatch.setattr(custom_services, "_render_node", _fake_render_node)

    await custom_services._execute_buy(message, state, 77)

    assert reserve_calls == [2]
    assert claim_calls == []
    assert delivery_calls and delivery_calls[0]["lang"] == "en"
    assert any("Purchased successfully" in row["text"] for row in message.answers)


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
    assert notified
    assert any("Reservation created successfully" in row["text"] for row in message.answers)
