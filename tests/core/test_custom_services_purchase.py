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

    async def update_data(self, **kwargs):
        self._data.update(kwargs)


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
async def test_show_buy_confirm_edits_message_and_omits_repeated_product_info(monkeypatch):
    state = _FakeState(
        {
            "buy_service_name": "PayPal",
            "buy_unit_price": 2.0,
            "buy_is_preorder": False,
        }
    )
    message = _FakeMessage()
    endpoint = {
        "_id": "ep1",
        "name": "PayPal",
        "price": 2.0,
        "available_qty": 5,
        "product_info_text": "Customer-facing description",
    }

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)

    await custom_services._show_buy_confirm(message, state, endpoint, 1)

    assert not message.answers
    assert message.edits
    text = message.edits[-1]["text"]
    assert "Confirm purchase" in text
    assert "Product: PayPal" in text
    assert "Total: 2.00" in text
    assert "Available Qty" not in text
    assert "Customer-facing description" not in text
    assert "Quantity:" not in text


@pytest.mark.asyncio
async def test_start_buy_endpoint_skips_quantity_screen_for_single_item_services(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=222)

    class _Callback:
        data = "cstm:buy:ep1"
        from_user = SimpleNamespace(id=77)

        def __init__(self):
            self.bot = _Bot()
            self.message = _FakeMessage()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep1",
            "node_type": "endpoint",
            "reseller_id": 500,
            "delivery_type": "inventory",
            "available_qty": 5,
            "inventory_items": [
                "account1",
                "account2",
                "account3",
                "account4",
                "account5",
            ],
            "price": 2.0,
            "name": "PayPal",
            "parent_id": "folder1",
            "min_qty": 1,
        }

    async def _fake_main(_bot_id):
        return False

    async def _fake_resolve_reseller(_user_id, _bot_id):
        return 500

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)
    monkeypatch.setattr(custom_services, "_resolve_user_reseller", _fake_resolve_reseller)

    state = _FakeState({})
    callback = _Callback()
    await custom_services.start_buy_endpoint(callback, state)

    assert state._data["buy_pending_qty"] == 1
    assert callback.message.edits
    text = callback.message.edits[-1]["text"]
    assert "Confirm purchase" in text
    assert "Choose quantity" not in text
    assert "Quantity:" not in text


@pytest.mark.asyncio
async def test_stock_save_and_add_another_keeps_append_entry_open(monkeypatch):
    class _Callback:
        data = "cstm:stocksaveadd"
        from_user = SimpleNamespace(id=77)

        def __init__(self):
            self.bot = SimpleNamespace()
            self.message = _FakeMessage()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    state = _FakeState(
        {
            "delivery_endpoint_id": "ep1",
            "delivery_return_node_id": "ep1",
            "delivery_stock_mode": "append",
            "custom_catalog_type": "custom",
            "delivery_preview_items": ["PayPal: seller@example.com\nPassword: pass-1"],
            "delivery_preview_raw_payload": "PayPal: seller@example.com\nPassword: pass-1",
            "delivery_preview_warnings": [],
        }
    )
    endpoint = {
        "_id": "ep1",
        "node_type": "endpoint",
        "reseller_id": 500,
        "name": "PayPal",
        "available_qty": 1,
        "delivery_type": "inventory",
    }
    appended = []

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_can_manage_builder(_user_id, _bot):
        return True

    async def _fake_builder_catalog_owner_id(_user_id, _bot, _data):
        return 500

    async def _fake_append_endpoint_inventory(*_args, **kwargs):
        appended.extend(kwargs["inventory_items"])
        return endpoint

    async def _fake_record_stock_event_safe(*_args, **_kwargs):
        return None

    async def _fake_record_builder_audit(*_args, **_kwargs):
        return None

    async def _fake_auto_fulfill_inventory_preorders(**_kwargs):
        return []

    async def _fake_get_node(_node_id, **_kwargs):
        return endpoint

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "_can_manage_builder", _fake_can_manage_builder)
    monkeypatch.setattr(custom_services, "_builder_catalog_owner_id", _fake_builder_catalog_owner_id)
    monkeypatch.setattr(custom_services, "append_endpoint_inventory", _fake_append_endpoint_inventory)
    monkeypatch.setattr(custom_services, "_record_stock_event_safe", _fake_record_stock_event_safe)
    monkeypatch.setattr(custom_services, "_record_builder_audit", _fake_record_builder_audit)
    monkeypatch.setattr(custom_services, "_auto_fulfill_inventory_preorders", _fake_auto_fulfill_inventory_preorders)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)

    callback = _Callback()
    await custom_services.save_delivery_stock_preview(callback, state)

    assert appended == ["PayPal: seller@example.com\nPassword: pass-1"]
    assert state.cleared is False
    assert state.state == custom_services.CustomBuilderStates.waiting_delivery_payload
    assert state._data["delivery_stock_mode"] == "append"
    assert state._data["delivery_preview_items"] == []
    assert callback.message.edits
    assert "Send the next stock item" in callback.message.edits[-1]["text"]
    callbacks = [
        btn.callback_data
        for row in callback.message.edits[-1]["kwargs"]["reply_markup"].inline_keyboard
        for btn in row
    ]
    assert "cstm:stockdone" in callbacks


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
    assert "Purchase successful" in message.edits[-1]["text"]
    assert "Product: Mailer" in message.edits[-1]["text"]
    assert "Quantity: 2" in message.edits[-1]["text"]
    assert "Total: 7.00" in message.edits[-1]["text"]
    assert "Order details:" in message.edits[-1]["text"]
    assert "payload" in message.edits[-1]["text"]
    assert "Digital Delivery" not in message.edits[-1]["text"]
    assert "Remaining stock" not in message.edits[-1]["text"]


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
async def test_reseller_bot_cannot_start_custom_service_preorder(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=222)

    class _Callback:
        data = "cstm:buy:ep3"
        from_user = SimpleNamespace(id=77)
        message = None

        def __init__(self):
            self.bot = _Bot()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep3",
            "node_type": "endpoint",
            "reseller_id": 500,
            "delivery_type": "inventory",
            "available_qty": 0,
            "inventory_items": [],
            "price": 4.0,
            "name": "PayPal Accounts",
            "preorder_enabled": True,
        }

    async def _fake_main(_bot_id):
        return False

    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)

    callback = _Callback()
    await custom_services.start_buy_endpoint(callback, _FakeState({}))

    assert callback.answers
    assert callback.answers[-1]["kwargs"].get("show_alert") is True
    assert "not ready" in callback.answers[-1]["text"].lower()


@pytest.mark.asyncio
async def test_main_bot_rejects_buy_for_non_owner_catalog(monkeypatch):
    class _Bot:
        async def get_me(self):
            return SimpleNamespace(id=111)

    class _Callback:
        data = "cstm:buy:ep1"
        from_user = SimpleNamespace(id=77)
        message = None

        def __init__(self):
            self.bot = _Bot()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": str(text or ""), "kwargs": kwargs})

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_get_node(_node_id, **_kwargs):
        return {
            "_id": "ep1",
            "node_type": "endpoint",
            "reseller_id": 500,
            "delivery_type": "text",
            "delivery_text": "payload",
            "available_qty": 1,
            "price": 2.0,
            "name": "Foreign Catalog Item",
        }

    async def _fake_main(_bot_id):
        return True

    monkeypatch.setattr(custom_services, "OWNER_ID", 9001)
    monkeypatch.setattr(custom_services, "get_user", _fake_get_user)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "is_main_bot", _fake_main)

    callback = _Callback()
    await custom_services.start_buy_endpoint(callback, _FakeState({}))

    assert callback.answers
    assert callback.answers[-1]["kwargs"].get("show_alert") is True
    assert "access" in callback.answers[-1]["text"].lower()


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


@pytest.mark.asyncio
async def test_reject_custom_preorder_refunds_and_notifies(monkeypatch):
    calls = {"refunds": [], "details": [], "statuses": [], "notified": []}
    preorder = {
        "_id": "pre1",
        "endpoint_id": "ep3",
        "catalog_owner_id": 500,
        "wallet_scope_id": 500,
        "catalog_type": "custom",
        "buyer_user_id": 77,
        "order_id": "order3",
        "qty": 1,
        "total_price": 4.0,
        "status": "pending",
    }

    class _Message:
        text = "Custom Service Preorder"

        async def edit_text(self, text, **kwargs):
            self.text = text

    class _Callback:
        data = "custom_preorder:reject:pre1"
        from_user = SimpleNamespace(id=9001)
        bot = SimpleNamespace()
        message = _Message()

        def __init__(self):
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    async def _fake_get_preorder(_preorder_id):
        return dict(preorder)

    async def _fake_refund(*args, **kwargs):
        calls["refunds"].append((args, kwargs))
        return True, "Refund Success"

    async def _fake_mark_refunding(_preorder_id, *, actor_id):
        return {**preorder, "status": "refunding", "refunding_by": actor_id}

    async def _fake_mark_rejected(_preorder_id, *, actor_id, reason=""):
        return {**preorder, "status": "rejected", "rejected_by": actor_id, "reject_reason": reason}

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
    monkeypatch.setattr(custom_services.FinancialManager, "refund_custom_purchase", _fake_refund)
    monkeypatch.setattr(custom_services, "mark_preorder_refunding", _fake_mark_refunding)
    monkeypatch.setattr(custom_services, "mark_preorder_rejected", _fake_mark_rejected)
    monkeypatch.setattr(custom_services, "get_node", _fake_get_node)
    monkeypatch.setattr(custom_services, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(custom_services, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(custom_services, "_notify_preorder_refunded_user", _fake_notify)

    callback = _Callback()
    await custom_services.reject_custom_preorder(callback)

    assert calls["refunds"]
    assert calls["refunds"][0][0][:3] == (77, "order3", 4.0)
    assert calls["statuses"] == [("order3", "refunded")]
    assert calls["details"][0][1]["custom_preorder_rejected"] is True
    assert calls["notified"]
    assert callback.answers[-1]["text"] == "Preorder refunded"


@pytest.mark.asyncio
async def test_show_pending_preorders_lists_orders(monkeypatch):
    rows = [
        {
            "_id": "abcdef123456",
            "service_name": "PayPal Accounts",
            "buyer_user_id": 77,
            "qty": 2,
            "total_price": 8.0,
        }
    ]

    class _Message:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, **kwargs):
            self.edits.append({"text": text, "kwargs": kwargs})

    class _Callback:
        from_user = SimpleNamespace(id=9001)
        bot = SimpleNamespace()

        def __init__(self):
            self.message = _Message()
            self.answers = []

        async def answer(self, text=None, **kwargs):
            self.answers.append({"text": text, "kwargs": kwargs})

    async def _fake_list_pending_preorders(**_kwargs):
        return list(rows)

    monkeypatch.setattr(custom_services, "list_pending_preorders", _fake_list_pending_preorders)

    callback = _Callback()
    await custom_services._show_pending_preorders(callback, catalog_owner_id=500)

    assert callback.message.edits
    assert "PayPal Accounts" in callback.message.edits[-1]["text"]
    markup = callback.message.edits[-1]["kwargs"]["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "custom_preorder:view:abcdef123456"
