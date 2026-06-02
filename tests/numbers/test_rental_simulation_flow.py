import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.getcwd())


class _DummyMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=555)
        self.edits: list[dict] = []
        self.answers: list[dict] = []
        self.message_id = 777
        self.bot = SimpleNamespace(get_me=self._get_me)

    async def _get_me(self):
        return SimpleNamespace(id=8147766487)

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.edits.append(
            {
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return self

    async def answer(self, text, reply_markup=None, parse_mode=None):
        self.answers.append(
            {
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return self


class _DummyCallback:
    def __init__(self, data: str, user_id: int = 7417429062):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _DummyMessage()
        self.answers: list[dict] = []

    async def answer(self, text=None, show_alert=None, **kwargs):
        self.answers.append({"text": text, "show_alert": show_alert, **kwargs})


class _DummyState:
    def __init__(self, data: dict):
        self.data = dict(data)
        self.states: list[object] = []

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.states.append(value)

    async def clear(self):
        self.data.clear()


@pytest.mark.asyncio
async def test_simulated_temp_purchase_success_flow(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    order_id = "507f1f77bcf86cd799439012"
    created_order = {
        "_id": order_id,
        "status": "draft",
        "user_id": 7417429062,
        "reseller_id": 7417429062,
        "service_id": "gmail",
        "selling_price": 0.45,
        "base_price": 0.31,
    }
    calls: dict[str, object] = {"details": [], "events": []}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_trust_gate(**kwargs):
        return {"allowed": True}

    async def _fake_resolve_user_reseller(user_id, bot_id):
        assert user_id == 7417429062
        assert bot_id == 8147766487
        return user_id

    async def _fake_create_order(**kwargs):
        calls["create_order"] = dict(kwargs)
        return dict(created_order)

    async def _fake_update_order_details(raw_order_id, patch):
        calls["details"].append((str(raw_order_id), dict(patch)))

    async def _fake_update_order_status(raw_order_id, status):
        calls.setdefault("statuses", []).append((str(raw_order_id), status))

    async def _fake_process_core_purchase(**kwargs):
        calls["wallet_charge"] = dict(kwargs)
        return True, "OK"

    async def _fake_charge_order_or_raise(**kwargs):
        calls["wallet_charge"] = {
            "sale_price": kwargs["final_price"],
            "cost_price": kwargs["cost_price"],
            "user_id": kwargs["user_id"],
            "order_id": kwargs["order_id"],
            "reseller_id": kwargs["reseller_id"],
        }

    async def _fake_buy_number_from_provider(**kwargs):
        calls["buy_provider"] = dict(kwargs)
        return {
            "success": True,
            "order_id": "tv_001",
            "number": "+15550002222",
            "pool": "main",
            "reuse_warranty_sec": 900,
        }

    async def _fake_provision_charged_temp_order(**kwargs):
        buy_res = await _fake_buy_number_from_provider(
            provider_code=kwargs["provider_code"],
            api_service_name=kwargs["api_service"],
            country=kwargs["country"],
            state=kwargs["state"],
            dry_run=False,
            purchase_options=kwargs.get("purchase_options") or {},
        )
        await _fake_update_order_details(
            kwargs["order_id"],
            {
                "provider_order_id": buy_res["order_id"],
                "provider": kwargs["provider_code"],
                "provider_number": buy_res["number"],
                "provider_pool": buy_res["pool"],
                "number_mode": kwargs.get("number_mode", "temp"),
                "temp_reuse_warranty_sec": buy_res["reuse_warranty_sec"],
            },
        )
        await _fake_update_order_status(kwargs["order_id"], "success")
        return {
            "provider_order_id": buy_res["order_id"],
            "number": buy_res["number"],
            "interval_sec": 5,
            "reuse_warranty_sec": buy_res["reuse_warranty_sec"],
        }

    async def _fake_log_number_event_from_order(order, event, **kwargs):
        calls["events"].append((event, kwargs))

    async def _fake_log_temp_event(order, event, payload):
        calls.setdefault("temp_events", []).append((event, payload))

    async def _fake_safe_edit_message(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        calls["final_message"] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }

    async def _fake_queue_temp_waiter(**kwargs):
        calls["queued_waiter"] = kwargs

    async def _fake_get_order(raw_order_id):
        if str(raw_order_id) == order_id:
            return {
                **created_order,
                "status": "success",
                "provider": "telabot",
                "provider_order_id": "tv_001",
                "provider_number": "+15550002222",
            }
        return None

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_evaluate_temp_trust_gate", _fake_trust_gate)
    monkeypatch.setattr(hb, "_resolve_user_reseller", _fake_resolve_user_reseller)
    monkeypatch.setattr(hb, "create_order", _fake_create_order)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb, "charge_order_or_raise", _fake_charge_order_or_raise)
    monkeypatch.setattr(hb, "provision_charged_temp_order", _fake_provision_charged_temp_order)
    monkeypatch.setattr(hb, "_log_number_event_from_order", _fake_log_number_event_from_order)
    monkeypatch.setattr(hb, "_log_temp_event", _fake_log_temp_event)
    monkeypatch.setattr(hb, "_safe_edit_message", _fake_safe_edit_message)
    monkeypatch.setattr(hb, "_queue_temp_waiter", _fake_queue_temp_waiter)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "_safe_callback_answer", lambda *args, **kwargs: __import__("asyncio").sleep(0, result=True))
    monkeypatch.setattr(hb, "_best_effort_edit_text", lambda *args, **kwargs: __import__("asyncio").sleep(0, result=True))

    state = _DummyState(
        {
            "selected_provider": "telabot",
            "api_service": "google",
            "country": "1",
            "state": "none",
            "service": "gmail",
            "final_price": 0.45,
            "base_price": 0.31,
        }
    )
    callback = _DummyCallback("buy:confirm")

    await hb.confirm_buy_process(callback, state)

    assert calls["create_order"]["service_id"] == "gmail"
    assert calls["wallet_charge"]["sale_price"] == 0.45
    assert calls["buy_provider"]["provider_code"] == "telabot"
    assert calls["buy_provider"]["api_service_name"] == "google"
    assert any(status == "success" for _, status in calls["statuses"])
    assert calls["final_message"]["parse_mode"] == "HTML"
    assert calls["queued_waiter"]["lang"] == "en"
    assert state.data == {}


@pytest.mark.asyncio
async def test_hidden_temp_provider_is_rejected_server_side(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict[str, object] = {}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_safe_callback_answer(*args, **kwargs):
        calls["answer"] = {"args": args, "kwargs": kwargs}
        return True

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_safe_callback_answer", _fake_safe_callback_answer)

    state = _DummyState(
        {
            "available_prices": {
                "nonvoip": {
                    "price": 0.3,
                    "base_price": 0.2,
                    "api_service_name": "gmail",
                    "available_for_buy": True,
                }
            }
        }
    )
    callback = _DummyCallback("buy_provider:nonvoip")

    await hb.provider_selected(callback, state)

    assert calls["answer"]["kwargs"]["show_alert"] is True
    assert state.states == []


@pytest.mark.asyncio
async def test_simulated_temp_second_code_flow(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    order_id = "507f1f77bcf86cd799439013"
    order = {
        "_id": order_id,
        "status": "success",
        "number_mode": "temp",
        "user_id": 7417429062,
        "reseller_id": 7417429062,
        "provider": "textverified",
        "provider_order_id": "tv_001",
        "provider_number": "+15550003333",
        "service_id": "gmail",
        "temp_service_key": "gmail",
        "temp_api_service": "google",
        "temp_country": "1",
        "temp_state": "none",
        "selling_price": 1.0,
        "base_price": 0.6,
        "provisioning_state": "provisioned",
        "created_at": datetime.now(UTC),
        "temp_first_sms_at": datetime.now(UTC) - timedelta(minutes=5),
        "temp_reuse_warranty_sec": 900,
    }
    calls: dict[str, object] = {"details": []}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_load_user_order(raw_id, user_id):
        assert raw_id == order_id
        assert user_id == 7417429062
        return order_id, dict(order)

    async def _fake_provider_resend(provider, provider_order_id):
        calls["provider_resend"] = (provider, provider_order_id)
        return {"success": True, "order_id": "tv_002", "number": "+15550004444"}

    async def _fake_resolve_user_reseller(user_id, bot_id):
        return user_id

    async def _fake_create_order(**kwargs):
        calls["create_order"] = dict(kwargs)
        return {"_id": "507f1f77bcf86cd799439014"}

    async def _fake_update_order_details(raw_order_id, patch):
        calls["details"].append((str(raw_order_id), dict(patch)))

    async def _fake_update_order_status(raw_order_id, status):
        calls.setdefault("statuses", []).append((str(raw_order_id), status))

    async def _fake_process_core_purchase(**kwargs):
        calls["wallet_charge"] = dict(kwargs)
        return True, "OK"

    async def _fake_charge_order_or_raise(**kwargs):
        calls["wallet_charge"] = {
            "sale_price": kwargs["final_price"],
            "cost_price": kwargs["cost_price"],
            "user_id": kwargs["user_id"],
            "order_id": kwargs["order_id"],
            "reseller_id": kwargs["reseller_id"],
        }

    async def _fake_log_temp_event(order_obj, event, payload):
        calls.setdefault("temp_events", []).append((event, payload))

    async def _fake_safe_edit_message(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        calls["final_message"] = text

    async def _fake_get_order(raw_order_id):
        if str(raw_order_id) == order_id:
            return {**order, "provider_order_id": "tv_002", "provider_number": "+15550004444"}
        return None

    async def _fake_queue_temp_waiter(**kwargs):
        calls["queued_waiter"] = kwargs

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_load_user_order", _fake_load_user_order)
    monkeypatch.setattr(hb, "_provider_resend", _fake_provider_resend)
    monkeypatch.setattr(hb, "_resolve_user_reseller", _fake_resolve_user_reseller)
    monkeypatch.setattr(hb, "create_order", _fake_create_order)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb.FinancialManager, "process_core_purchase", classmethod(lambda cls, **kwargs: _fake_process_core_purchase(**kwargs)))
    monkeypatch.setattr(hb, "_log_temp_event", _fake_log_temp_event)
    monkeypatch.setattr(hb, "_safe_edit_message", _fake_safe_edit_message)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "_queue_temp_waiter", _fake_queue_temp_waiter)
    monkeypatch.setattr(hb, "_safe_callback_answer_or_message", lambda *args, **kwargs: __import__("asyncio").sleep(0, result=True))

    callback = _DummyCallback(f"temp:second:{order_id}")
    await hb.temp_second_code(callback)

    assert calls["provider_resend"] == ("textverified", "tv_001")
    assert calls["create_order"]["service_id"] == "gmail:second_code"
    assert calls["wallet_charge"]["sale_price"] == 0.5
    assert any(str(raw_id) == "507f1f77bcf86cd799439014" and patch.get("number_mode") == "second_code_charge" for raw_id, patch in calls["details"])
    assert any(str(raw_id) == order_id and patch.get("provider_order_id") == "tv_002" for raw_id, patch in calls["details"])
    assert calls["queued_waiter"]["is_second_code"] is True
    event_names = [event for event, _payload in calls["temp_events"]]
    assert event_names == ["second_code_attempted", "second_code_provider_success", "second_code_requested"]
    assert calls["temp_events"][-1][1]["seconds_since_first_code"] is not None


@pytest.mark.asyncio
async def test_simulated_temp_cancel_callback_success(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    order_id = "507f1f77bcf86cd799439015"
    order = {
        "_id": order_id,
        "status": "success",
        "user_id": 7417429062,
        "reseller_id": 7417429062,
        "provider": "textverified",
        "provider_order_id": "tv_cancel",
        "selling_price": 1.0,
        "base_price": 0.5,
        "created_at": datetime.now(UTC) - timedelta(minutes=10),
        "temp_codes_count": 0,
        "temp_codes": [],
    }
    calls: dict[str, object] = {}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_load_user_order(raw_id, user_id):
        return order_id, dict(order)

    async def _fake_cancel_and_refund_temp_order(**kwargs):
        calls["cancel_refund"] = dict(kwargs)
        return {"success": True}

    async def _fake_safe_edit_message(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        calls["final_message"] = {"text": text, "reply_markup": reply_markup}

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_load_user_order", _fake_load_user_order)
    monkeypatch.setattr(hb, "_cancel_and_refund_temp_order", _fake_cancel_and_refund_temp_order)
    monkeypatch.setattr(hb, "_safe_edit_message", _fake_safe_edit_message)
    monkeypatch.setattr(hb, "_safe_callback_answer", lambda *args, **kwargs: __import__("asyncio").sleep(0, result=True))

    callback = _DummyCallback(f"temp:cancel:{order_id}")
    await hb.temp_cancel_and_refund(callback)

    assert calls["cancel_refund"]["reason"] == "user_after_timeout"
    assert calls["final_message"]["text"]
    assert calls["final_message"]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_simulated_rental_fetch_sms_finish_and_wake(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    order_id = "507f1f77bcf86cd799439016"
    order = {
        "_id": order_id,
        "status": "success",
        "user_id": 7417429062,
        "reseller_id": 7417429062,
        "provider": "textverified",
        "provider_order_id": "lr_101",
        "service_id": "gmail:rental",
        "selling_price": 7.0,
        "base_price": 6.0,
    }
    calls: dict[str, object] = {"details": [], "events": []}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_load_user_order(raw_id, user_id):
        return order_id, dict(order)

    async def _fake_rental_sms_state(order_obj, *, source=""):
        calls["sms_service"] = (order_obj["provider"], order_obj["provider_order_id"])
        calls["sms_source"] = source
        return {"ok": True, "messages": ["265464", "871122"], "order": dict(order_obj)}

    async def _fake_update_order_details(raw_order_id, patch):
        calls["details"].append((str(raw_order_id), dict(patch)))

    async def _fake_get_order(raw_order_id):
        return dict(order)

    async def _fake_notice(**kwargs):
        calls["notice"] = kwargs

    async def _fake_log_rental_event(**kwargs):
        calls["events"].append(kwargs.get("event"))

    async def _fake_finish_rental_order(order_obj, *, source=""):
        calls["finish_service"] = (order_obj["provider"], order_obj["provider_order_id"])
        calls["finish_source"] = source
        calls.setdefault("number_events", []).append("rental_finished")
        return {"ok": True, "order": dict(order_obj)}

    async def _fake_wake_rental_order(order_obj, *, source=""):
        calls["wake_service"] = (order_obj["provider"], order_obj["provider_order_id"])
        calls["wake_source"] = source
        calls.setdefault("number_events", []).append("rental_wake_ok")
        return {"ok": True, "order": dict(order_obj)}

    async def _fake_log_number_event_from_order(order_obj, event, **kwargs):
        calls.setdefault("number_events", []).append(event)

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_load_user_order", _fake_load_user_order)
    monkeypatch.setattr(hb, "rental_sms_state", _fake_rental_sms_state)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "_maybe_send_purchase_charge_confirmed_notice", _fake_notice)
    monkeypatch.setattr(hb, "_log_rental_event", _fake_log_rental_event)
    monkeypatch.setattr(hb, "finish_rental_order", _fake_finish_rental_order)
    monkeypatch.setattr(hb, "wake_rental_order", _fake_wake_rental_order)
    monkeypatch.setattr(hb, "_log_number_event_from_order", _fake_log_number_event_from_order)
    monkeypatch.setattr(hb, "_safe_callback_answer", lambda *args, **kwargs: __import__("asyncio").sleep(0, result=True))

    sms_callback = _DummyCallback(f"rent:sms:{order_id}")
    await hb.rent_fetch_sms(sms_callback)

    assert calls["sms_service"] == ("textverified", "lr_101")
    assert calls["sms_source"] == "numbers_telegram"
    assert any("rental_sms_count" in patch for _, patch in calls["details"])
    assert sms_callback.message.answers[-1]["text"].count("- ") == 2

    finish_callback = _DummyCallback(f"rent:finish:{order_id}")
    await hb.rent_finish(finish_callback)
    assert calls["finish_service"] == ("textverified", "lr_101")
    assert calls["finish_source"] == "numbers_telegram"
    assert "rental_finished" in calls["number_events"]

    wake_callback = _DummyCallback(f"rent:wake:{order_id}")
    await hb.rent_wake(wake_callback)
    assert calls["wake_service"] == ("textverified", "lr_101")
    assert calls["wake_source"] == "numbers_telegram"
    assert "rental_wake_ok" in calls["number_events"]


@pytest.mark.asyncio
async def test_simulated_rental_purchase_then_renew_after_two_hours(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    order_id = "507f1f77bcf86cd799439011"
    created_order = {
        "_id": order_id,
        "status": "draft",
        "user_id": 7417429062,
        "reseller_id": 7417429062,
        "service_id": "gmail:rental",
        "selling_price": 7.0,
        "base_price": 6.0,
    }
    persisted_order = {
        **created_order,
        "status": "success",
        "provider": "textverified",
        "provider_order_id": "lr_001",
        "provider_number": "+15550001111",
        "rental_country": "1",
        "rental_country_name": "United States",
        "rental_duration_label": "24h (1d)",
        "rental_duration_hours": 24,
        "rental_is_renewable": True,
        "rental_billing_cycle_label": "Auto renew",
        "rental_started_at": datetime.now(UTC) - timedelta(hours=2),
    }
    calls: dict[str, object] = {"details": [], "events": []}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_resolve_user_reseller(user_id, bot_id):
        assert user_id == 7417429062
        assert bot_id == 8147766487
        return user_id

    async def _fake_create_order(**kwargs):
        calls["create_order"] = dict(kwargs)
        return dict(created_order)

    async def _fake_update_order_details(raw_order_id, patch):
        calls["details"].append((str(raw_order_id), dict(patch)))
        persisted_order.update(patch)

    async def _fake_update_order_status(raw_order_id, status):
        calls.setdefault("statuses", []).append((str(raw_order_id), status))
        persisted_order["status"] = status

    async def _fake_process_core_purchase(**kwargs):
        calls["wallet_charge"] = dict(kwargs)
        return True, "OK"

    async def _fake_charge_order_or_raise(**kwargs):
        calls["wallet_charge"] = {
            "sale_price": kwargs["final_price"],
            "cost_price": kwargs["cost_price"],
            "user_id": kwargs["user_id"],
            "order_id": kwargs["order_id"],
            "reseller_id": kwargs["reseller_id"],
        }

    async def _fake_rent_number_from_provider(provider_code, api_service_name, country, duration, option_meta=None):
        calls["rent_provider"] = {
            "provider_code": provider_code,
            "api_service_name": api_service_name,
            "country": country,
            "duration": duration,
            "option_meta": dict(option_meta or {}),
        }
        return {
            "success": True,
            "order_id": "lr_001",
            "number": "+15550001111",
            "price": 6.0,
            "end_date": "2026-04-01T00:00:00Z",
            "billing_cycle_id": "bc_001",
            "refund_can_refund": True,
        }

    async def _fake_provision_charged_rental_order(**kwargs):
        rent_res = await _fake_rent_number_from_provider(
            kwargs["provider_code"],
            kwargs["api_service"],
            kwargs["country"],
            kwargs["duration"],
            kwargs.get("option_meta") or {},
        )
        await _fake_update_order_details(
            kwargs["order_id"],
            {
                "provider_order_id": rent_res["order_id"],
                "provider": kwargs["provider_code"],
                "provider_number": rent_res["number"],
                "number_mode": "rental",
                "rental_is_renewable": kwargs.get("is_renewable", False),
                "rental_billing_cycle_id": rent_res["billing_cycle_id"],
                "rental_end_date": rent_res["end_date"],
            },
        )
        await _fake_update_order_status(kwargs["order_id"], "success")
        return {
            "provider_order_id": rent_res["order_id"],
            "number": rent_res["number"],
        }

    async def _fake_log_number_event_from_order(order, event, **kwargs):
        calls["events"].append((event, kwargs))

    async def _fake_log_rental_event(**kwargs):
        calls.setdefault("rental_events", []).append(kwargs.get("event"))

    async def _fake_best_effort_edit_text(message, text, reply_markup=None, parse_mode=None):
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

    async def _fake_load_user_order(raw_id, user_id):
        assert raw_id == order_id
        assert user_id == 7417429062
        return order_id, dict(persisted_order)

    async def _fake_renew_rental_order(*, order, user_id, idempotency_key, source=""):
        calls["renew_service"] = {
            "provider_code": order["provider"],
            "activation_id": order["provider_order_id"],
            "user_id": user_id,
            "idempotency_key": idempotency_key,
            "source": source,
        }
        await _fake_update_order_details(order["_id"], {"rental_last_renew_at": datetime.now(UTC)})
        return {"ok": True, "order": dict(order)}

    async def _fake_rental_refund_guard(**kwargs):
        calls["guard"] = dict(kwargs)

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_resolve_user_reseller", _fake_resolve_user_reseller)
    monkeypatch.setattr(hb, "create_order", _fake_create_order)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb, "charge_order_or_raise", _fake_charge_order_or_raise)
    monkeypatch.setattr(hb, "provision_charged_rental_order", _fake_provision_charged_rental_order)
    monkeypatch.setattr(hb, "_log_number_event_from_order", _fake_log_number_event_from_order)
    monkeypatch.setattr(hb, "_log_rental_event", _fake_log_rental_event)
    monkeypatch.setattr(hb, "_best_effort_edit_text", _fake_best_effort_edit_text)
    monkeypatch.setattr(hb, "_safe_callback_answer", lambda *args, **kwargs: __import__("asyncio").sleep(0, result=True))
    monkeypatch.setattr(hb, "_load_user_order", _fake_load_user_order)
    monkeypatch.setattr(hb, "renew_rental_order", _fake_renew_rental_order)
    monkeypatch.setattr(hb, "_rental_refund_guard", _fake_rental_refund_guard)

    purchase_state = _DummyState(
        {
            "lang": "en",
            "service": "gmail",
            "country": "1",
            "selected_rental_option": {
                "provider": "textverified",
                "api_service_name": "gmail",
                "country": "1",
                "country_name": "United States",
                "duration": 24,
                "duration_label": "24h (1d)",
                "price": 7.0,
                "base_price": 6.0,
                "tv_is_renewable": True,
                "tv_duration_key": "oneDay",
                "rental_billing_cycle_label": "Auto renew",
            },
        }
    )
    purchase_callback = _DummyCallback("rent:confirm:final")

    await hb.rent_confirm_process(purchase_callback, purchase_state)

    assert calls["create_order"]["service_id"] == "gmail:rental"
    assert calls["wallet_charge"]["sale_price"] == 7.0
    assert calls["rent_provider"]["provider_code"] == "textverified"
    assert calls["rent_provider"]["duration"] == 24
    assert persisted_order["provider_order_id"] == "lr_001"
    assert persisted_order["rental_is_renewable"] is True
    assert any(status == "success" for _, status in calls["statuses"])
    await asyncio.sleep(0)
    assert calls["guard"]["order_id"] == order_id
    assert purchase_callback.message.edits[-1]["reply_markup"] is not None

    renew_callback = _DummyCallback(f"rent:renew:{order_id}")
    await hb.rent_renew(renew_callback)

    assert calls["renew_service"]["provider_code"] == "textverified"
    assert calls["renew_service"]["activation_id"] == "lr_001"
    assert calls["renew_service"]["idempotency_key"] == f"telegram:rental_renew:7417429062:{order_id}"
    assert calls["renew_service"]["source"] == "numbers_telegram"
    renew_detail_patches = [patch for _, patch in calls["details"] if "rental_last_renew_at" in patch]
    assert renew_detail_patches, "renew flow should persist rental_last_renew_at"
