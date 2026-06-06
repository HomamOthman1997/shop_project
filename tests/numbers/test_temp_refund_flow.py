import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.getcwd())


def test_voice_waiting_order_counts_active_for_trust_gate():
    from services.numbers.handlers.temp_order_utils import _is_temp_order_active_for_trust_gate

    now = datetime.now(UTC)
    order = {
        "number_mode": "voice",
        "temp_wait_state": "waiting_for_call",
        "temp_wait_started_at": now - timedelta(seconds=30),
        "temp_wait_timeout_sec": 300,
    }

    assert _is_temp_order_active_for_trust_gate(order, now=now) is True


def test_voice_received_call_counts_active_for_trust_gate():
    from services.numbers.handlers.temp_order_utils import _is_temp_order_active_for_trust_gate

    now = datetime.now(UTC)
    order = {
        "number_mode": "voice",
        "temp_wait_state": "call_received",
        "temp_wait_started_at": now - timedelta(seconds=30),
        "temp_wait_timeout_sec": 300,
        "temp_reuse_warranty_sec": 300,
    }

    assert _is_temp_order_active_for_trust_gate(order, now=now) is True


@pytest.mark.asyncio
async def test_cancel_and_refund_temp_order_success(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {}

    class _DummyProvider:
        async def cancel(self, activation_id):
            calls["provider_cancel"] = activation_id
            return {"success": True, "raw": {"ok": 1}}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, user_id, order_id, sale_price, cost_price, reseller_id=None):
            calls["refund"] = {
                "user_id": user_id,
                "order_id": order_id,
                "sale_price": sale_price,
                "cost_price": cost_price,
                "reseller_id": reseller_id,
            }
            return True, "OK"

    async def _fake_update_order_status(order_id, status):
        calls["status"] = {"order_id": order_id, "status": status}

    async def _fake_update_order_details(order_id, patch):
        calls["details"] = {"order_id": order_id, "patch": patch}

    async def _fake_log_temp_event(order, event, payload=None):
        calls["event"] = {"event": event, "payload": payload or {}}

    monkeypatch.setitem(hb.PROVIDERS, "nonvoip", _DummyProvider())
    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "_log_temp_event", _fake_log_temp_event)

    order = {
        "_id": "oid-1",
        "status": "success",
        "user_id": 123,
        "reseller_id": 456,
        "provider": "nonvoip",
        "provider_order_id": "prov-123",
        "selling_price": 1.8,
        "base_price": 1.2,
        "temp_codes_count": 0,
        "temp_codes": [],
    }

    res = await hb._cancel_and_refund_temp_order(
        order_id="oid-1",
        order=order,
        actor_user_id=123,
        reason="auto_timeout_no_code",
        require_no_sms=True,
    )
    assert res["success"] is True
    assert calls["provider_cancel"] == "prov-123"
    assert calls["refund"]["order_id"] == "oid-1"
    assert calls["status"]["status"] == "cancelled"
    assert calls["details"]["patch"]["temp_cancel_reason"] == "auto_timeout_no_code"
    assert calls["event"]["event"] == "cancelled_refunded"


@pytest.mark.asyncio
async def test_cancel_and_refund_temp_order_blocked_if_code_received(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {}

    class _DummyProvider:
        async def cancel(self, activation_id):
            calls["provider_cancel"] = activation_id
            return {"success": True}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, *args, **kwargs):
            calls["refund"] = True
            return True, "OK"

    monkeypatch.setitem(hb.PROVIDERS, "smspool", _DummyProvider())
    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)

    order = {
        "_id": "oid-2",
        "status": "success",
        "user_id": 11,
        "reseller_id": 22,
        "provider": "smspool",
        "provider_order_id": "prov-999",
        "selling_price": 1.0,
        "base_price": 0.5,
        "temp_codes_count": 1,
        "temp_codes": ["1234"],
        "temp_last_code": "1234",
    }

    res = await hb._cancel_and_refund_temp_order(
        order_id="oid-2",
        order=order,
        actor_user_id=11,
        reason="user_after_timeout",
        require_no_sms=True,
    )
    assert res["success"] is False
    assert res["reason"] == "sms_received"
    assert "provider_cancel" not in calls
    assert "refund" not in calls


@pytest.mark.asyncio
async def test_cancel_and_refund_temp_order_recovers_provider_code_before_cancel(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {}

    class _DummyProvider:
        async def get_sms(self, activation_id):
            calls["provider_check"] = activation_id
            return {"success": True, "messages": "778899", "raw": {}}

        async def cancel(self, activation_id):
            calls["provider_cancel"] = activation_id
            return {"success": True}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, *args, **kwargs):
            calls["refund"] = True
            return True, "OK"

    async def _fake_update_order_details(order_id, patch):
        calls["patch"] = patch

    async def _fake_log_temp_event(order, event, payload=None):
        calls["event"] = (event, payload)

    monkeypatch.setitem(hb.PROVIDERS, "smspool", _DummyProvider())
    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "_log_temp_event", _fake_log_temp_event)

    order = {
        "_id": "oid-recovery",
        "status": "success",
        "user_id": 11,
        "reseller_id": 22,
        "provider": "smspool",
        "provider_order_id": "provider-1",
        "selling_price": 1.0,
        "base_price": 0.5,
        "temp_codes": [],
    }

    result = await hb._cancel_and_refund_temp_order(
        order_id=order["_id"],
        order=order,
        actor_user_id=11,
        reason="timeout",
        require_no_sms=True,
    )

    assert result == {"success": False, "reason": "sms_received", "provider_sms_recovered": True}
    assert calls["provider_check"] == "provider-1"
    assert calls["patch"]["temp_last_code"] == "778899"
    assert calls["event"][0] == "code_received_recovery"
    assert "provider_cancel" not in calls
    assert "refund" not in calls


@pytest.mark.asyncio
async def test_confirm_buy_does_not_retry_without_state(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls = {"buy": []}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_trust_gate(**kwargs):
        return {"allowed": True}

    async def _fake_reseller(_user_id, _bot_id):
        return 77

    async def _fake_create_order(**kwargs):
        return {"_id": "oid-temp"}

    async def _fake_update_order_details(order_id, patch):
        calls.setdefault("details", []).append((order_id, patch))

    async def _fake_update_order_status(order_id, status):
        calls["status"] = (order_id, status)

    class _DummyFinancialManager:
        @classmethod
        async def process_core_purchase(cls, **kwargs):
            return True, "OK"

        @classmethod
        async def refund_core_purchase(cls, *args, **kwargs):
            calls["refund"] = True
            return True, "OK"

    async def _fake_balance(*args, **kwargs):
        return 100.0

    async def _fake_best_effort(*args, **kwargs):
        return None

    async def _fake_charge_order_or_raise(**kwargs):
        return None

    async def _fake_buy_number_from_provider(**kwargs):
        calls["buy"].append(kwargs)
        return {"success": False, "raw": "state_not_available"}

    async def _fake_provision_charged_temp_order(**kwargs):
        await _fake_buy_number_from_provider(
            provider_code=kwargs["provider_code"],
            api_service_name=kwargs["api_service"],
            country=kwargs["country"],
            state=kwargs["state"],
            dry_run=False,
            purchase_options=kwargs.get("purchase_options") or {},
        )
        await _fake_update_order_status(kwargs["order_id"], "refunded")
        raise hb.ProviderProvisioningError("state_not_available", refund_ok=True, raw="state_not_available")

    class _DummyBot:
        async def get_me(self):
            return type("Me", (), {"id": 1})()

    class _DummyMessage:
        def __init__(self):
            self.bot = _DummyBot()
            self.chat = type("Chat", (), {"id": 10})()
            self.message_id = 20
            self.answers = []

        async def answer(self, *args, **kwargs):
            self.answers.append((args, kwargs))
            return None

        async def edit_text(self, *args, **kwargs):
            return None

    class _DummyState:
        def __init__(self):
            self.data = {
                "selected_provider": "textverified",
                "api_service": "google",
                "country": "US",
                "state": "CA",
                "service": "gmail",
                "final_price": 2.4,
                "base_price": 1.2,
            }

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def clear(self):
            self.data.clear()

    class _DummyCallback:
        def __init__(self):
            self.from_user = type("U", (), {"id": 5})()
            self.message = _DummyMessage()

        async def answer(self, *args, **kwargs):
            return None

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_evaluate_temp_trust_gate", _fake_trust_gate)
    monkeypatch.setattr(hb, "_resolve_user_reseller", _fake_reseller)
    monkeypatch.setattr(hb, "create_order", _fake_create_order)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(hb, "get_user_wallet_balance", _fake_balance)
    monkeypatch.setattr(hb, "_best_effort_edit_text", _fake_best_effort)
    monkeypatch.setattr(hb, "charge_order_or_raise", _fake_charge_order_or_raise)
    monkeypatch.setattr(hb, "provision_charged_temp_order", _fake_provision_charged_temp_order)
    monkeypatch.setattr(hb, "menu_for_current_bot", lambda *args, **kwargs: __import__("asyncio").sleep(0, result="MENU_KB"))

    callback = _DummyCallback()
    state = _DummyState()
    await hb.confirm_buy_process(callback, state)

    assert len(calls["buy"]) == 1
    assert calls["buy"][0]["state"] == "CA"
    assert calls["status"] == ("oid-temp", "refunded")
    assert state.data == {}
    assert callback.message.answers[-1][1]["reply_markup"] == "MENU_KB"


@pytest.mark.asyncio
async def test_evaluate_temp_trust_gate_blocks_when_active_temp_order_exists(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    async def _fake_list_user_open_temp_orders(user_id, limit=5):
        return [{"_id": "oid-1", "temp_wait_state": "waiting"}]

    monkeypatch.setattr(hb, "list_user_open_temp_orders", _fake_list_user_open_temp_orders)

    gate = await hb._evaluate_temp_trust_gate(
        user_id=7,
        service_id="gmail",
        provider_code="textverified",
    )

    assert gate["allowed"] is False
    assert gate["mode"] == "active_order"


@pytest.mark.asyncio
async def test_evaluate_temp_trust_gate_ignores_stale_waiting_order(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    old_created = datetime.now(UTC) - timedelta(hours=2)

    async def _fake_list_user_open_temp_orders(user_id, limit=5):
        return [
            {
                "_id": "oid-1",
                "temp_wait_state": "waiting",
                "created_at": old_created,
                "temp_wait_timeout_sec": 300,
            }
        ]

    async def _fake_get_active_user_temp_lock(**kwargs):
        return None

    async def _fake_snapshot(**kwargs):
        return {"positive": 0, "negative": 0, "score": 0}

    async def _fake_count_recent_negative_attempts(**kwargs):
        return 0

    monkeypatch.setattr(hb, "list_user_open_temp_orders", _fake_list_user_open_temp_orders)
    monkeypatch.setattr(hb.temp_number_stats_repo, "get_active_user_temp_lock", _fake_get_active_user_temp_lock)
    monkeypatch.setattr(hb.temp_number_stats_repo, "get_user_trust_snapshot", _fake_snapshot)
    monkeypatch.setattr(hb.temp_number_stats_repo, "count_recent_negative_attempts", _fake_count_recent_negative_attempts)

    gate = await hb._evaluate_temp_trust_gate(
        user_id=7,
        service_id="shopback",
        provider_code="textverified",
    )

    assert gate["allowed"] is True


@pytest.mark.asyncio
async def test_evaluate_temp_trust_gate_allows_two_recent_no_code_attempts_and_blocks_third(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls = {}

    async def _fake_list_user_open_temp_orders(user_id, limit=5):
        return []

    async def _fake_get_active_user_temp_lock(**kwargs):
        return None

    async def _fake_snapshot(**kwargs):
        return {"positive": 0, "negative": 0, "score": 0}

    attempts = {"value": 2}

    async def _fake_count_recent_negative_attempts(**kwargs):
        return attempts["value"]

    async def _fake_set_user_temp_lock(**kwargs):
        calls["lock"] = kwargs
        return kwargs

    monkeypatch.setattr(hb, "list_user_open_temp_orders", _fake_list_user_open_temp_orders)
    monkeypatch.setattr(hb.temp_number_stats_repo, "get_active_user_temp_lock", _fake_get_active_user_temp_lock)
    monkeypatch.setattr(hb.temp_number_stats_repo, "get_user_trust_snapshot", _fake_snapshot)
    monkeypatch.setattr(hb.temp_number_stats_repo, "count_recent_negative_attempts", _fake_count_recent_negative_attempts)
    monkeypatch.setattr(hb.temp_number_stats_repo, "set_user_temp_lock", _fake_set_user_temp_lock)

    gate = await hb._evaluate_temp_trust_gate(
        user_id=7,
        service_id="gmail",
        provider_code="textverified",
    )
    assert gate["allowed"] is False
    assert gate["mode"] == "purchase"
    assert calls["lock"]["reason"] == "recent_no_code_attempts_limit"
