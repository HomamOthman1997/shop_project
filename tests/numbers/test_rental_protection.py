import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.getcwd())


def test_rental_refund_warning_kind_defaults_and_explicit():
    import services.numbers.handlers.core_numbers_buy as hb

    assert hb._rental_refund_warning_kind("herosms", {}) == "protected"
    assert hb._rental_refund_warning_kind("textverified", {}) == "uncertain"
    assert hb._rental_refund_warning_kind("smspool", {"refund_known_false": True}) == "non_refundable"
    assert hb._rental_refund_warning_kind("smspool", {"refund_warning_kind": "protected"}) == "protected"
    assert hb._rental_refund_warning_kind("smspool", {"provider_can_refund": True}) == "protected"
    assert hb._rental_refund_warning_kind("textverified", {"refund_refundable_until": "2026-03-20T12:00:00Z"}) == "protected"
    assert hb._rental_refund_warning_kind("textverified", {"provider_can_refund": False}) == "non_refundable"


def test_rental_confirm_keyboard_goes_directly_to_final_confirmation():
    from services.numbers.keyboards.core_numbers_kb import rental_confirm_kb

    kb = rental_confirm_kb("en")
    assert kb.inline_keyboard[0][0].callback_data == "rent:confirm:final"


def test_rental_warning_kb_uses_second_confirmation_callback():
    from services.numbers.keyboards.core_numbers_kb import rental_warning_kb

    kb = rental_warning_kb("en")
    assert kb.inline_keyboard[0][0].callback_data == "rent:confirm:final"
    assert kb.inline_keyboard[1][0].callback_data == "rent:confirm:back"


@pytest.mark.asyncio
async def test_cancel_and_refund_rental_uses_provider_cancel_for_hero(monkeypatch):
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

    async def _fake_sync(*args, **kwargs):
        return {"success": True, "messages": [], "has_sms": False}

    async def _fake_update_order_status(order_id, status):
        calls["status"] = status

    async def _fake_update_order_details(order_id, patch):
        calls["details"] = patch

    async def _fake_log_rental_event(**kwargs):
        calls["event"] = kwargs.get("event")

    async def _unexpected_finish(*args, **kwargs):
        raise AssertionError("finish_rental_from_provider should not be used for HeroSMS auto-refund")

    monkeypatch.setitem(hb.PROVIDERS, "herosms", _DummyProvider())
    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(hb, "_sync_rental_sms_snapshot", _fake_sync)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "_log_rental_event", _fake_log_rental_event)
    monkeypatch.setattr(hb, "finish_rental_from_provider", _unexpected_finish)

    order = {
        "_id": "oid-hero",
        "status": "success",
        "user_id": 10,
        "reseller_id": 20,
        "provider": "herosms",
        "provider_order_id": "hero-1",
        "selling_price": 2.0,
        "base_price": 1.0,
    }

    res = await hb._cancel_and_refund_rental_order(
        order_id="oid-hero",
        order=order,
        actor_user_id=10,
        reason="hero_test",
        require_no_sms=True,
    )
    assert res["success"] is True
    assert calls["provider_cancel"] == "hero-1"
    assert calls["refund"]["order_id"] == "oid-hero"
    assert calls["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_and_refund_rental_uses_finish_for_smspool(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {}

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, *args, **kwargs):
            calls["refund"] = True
            return True, "OK"

    async def _fake_sync(*args, **kwargs):
        return {"success": True, "messages": [], "has_sms": False}

    async def _fake_finish(provider_code, activation_id):
        calls["finish"] = (provider_code, activation_id)
        return {"success": True, "raw": {"ok": 1}}

    async def _fake_update_order_status(order_id, status):
        calls["status"] = status

    async def _fake_update_order_details(order_id, patch):
        calls["details"] = patch

    async def _fake_log_rental_event(**kwargs):
        calls["event"] = kwargs.get("event")

    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(hb, "_sync_rental_sms_snapshot", _fake_sync)
    monkeypatch.setattr(hb, "finish_rental_from_provider", _fake_finish)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_order_status)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)
    monkeypatch.setattr(hb, "_log_rental_event", _fake_log_rental_event)

    order = {
        "_id": "oid-pool",
        "status": "success",
        "user_id": 10,
        "reseller_id": 20,
        "provider": "smspool",
        "provider_order_id": "pool-1",
        "selling_price": 2.0,
        "base_price": 1.0,
    }

    res = await hb._cancel_and_refund_rental_order(
        order_id="oid-pool",
        order=order,
        actor_user_id=10,
        reason="pool_test",
        require_no_sms=True,
    )
    assert res["success"] is True
    assert calls["finish"] == ("smspool", "pool-1")
    assert calls["refund"] is True
    assert calls["status"] == "cancelled"


@pytest.mark.asyncio
async def test_rental_exit_guard_prompts_user(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    class _DummyMessage:
        def __init__(self):
            self.from_user = type("U", (), {"id": 99})()
            self.answers = []

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

    class _DummyState:
        async def clear(self):
            return None

    async def _fake_orders(_user_id):
        return [
            {
                "_id": "507f1f77bcf86cd799439011",
                "provider": "herosms",
                "status": "success",
            }
        ]

    monkeypatch.setattr(hb, "_user_open_rentals_without_sms", _fake_orders)

    msg = _DummyMessage()
    handled = await hb._handle_rental_exit_message_guard(msg, _DummyState(), target="start", lang="en")
    assert handled is True
    assert len(msg.answers) == 1
    text, kb = msg.answers[0]
    assert "active rental number" in text
    assert kb.inline_keyboard[0][0].text == "Keep Number"
    assert kb.inline_keyboard[1][0].text == "Cancel & Refund"
    assert kb.inline_keyboard[0][0].callback_data == "rentguard:keep:start:all"


@pytest.mark.asyncio
async def test_rental_exit_guard_prompts_for_multiple_open_rentals(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    class _DummyMessage:
        def __init__(self):
            self.from_user = type("U", (), {"id": 99})()
            self.answers = []

        async def answer(self, text, reply_markup=None):
            self.answers.append((text, reply_markup))

    class _DummyState:
        async def clear(self):
            return None

    async def _fake_orders(_user_id):
        return [
            {"_id": "1", "provider": "smspool", "status": "success"},
            {"_id": "2", "provider": "herosms", "status": "success"},
        ]

    monkeypatch.setattr(hb, "_user_open_rentals_without_sms", _fake_orders)
    monkeypatch.setattr(hb, "_sync_rental_protection_snapshot", lambda *args, **kwargs: __import__("asyncio").sleep(0, result={"success": False}))
    monkeypatch.setattr(hb, "get_order", lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=None))

    msg = _DummyMessage()
    handled = await hb._handle_rental_exit_message_guard(msg, _DummyState(), target="main", lang="en")
    assert handled is True
    text, kb = msg.answers[0]
    assert "2 active rental numbers" in text
    assert kb.inline_keyboard[1][0].callback_data == "rentguard:cancel:main:all"


@pytest.mark.asyncio
async def test_rental_refund_guard_auto_cancels_near_cutoff(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {}
    order = {
        "_id": "oid-guard",
        "status": "success",
        "user_id": 33,
        "reseller_id": 44,
        "provider": "herosms",
        "provider_order_id": "hero-guard",
        "service_id": "paypal:rental",
        "rental_started_at": datetime.now(UTC) - timedelta(seconds=1190),
    }

    async def _fake_get_order(order_id):
        return order

    async def _fake_sync(*args, **kwargs):
        return {"success": True, "messages": [], "has_sms": False}

    async def _fake_cancel_and_refund(**kwargs):
        calls["cancel"] = kwargs
        return {"success": True}

    async def _fake_log_rental_event(**kwargs):
        calls["event"] = kwargs.get("event")

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "_sync_rental_sms_snapshot", _fake_sync)
    monkeypatch.setattr(hb, "_cancel_and_refund_rental_order", _fake_cancel_and_refund)
    monkeypatch.setattr(hb, "_log_rental_event", _fake_log_rental_event)
    monkeypatch.setattr(hb.asyncio, "sleep", _no_sleep)

    await hb._rental_refund_guard(order_id="oid-guard", actor_user_id=33)
    assert calls["cancel"]["order_id"] == "oid-guard"
    assert calls["cancel"]["reason"] == "herosms_guard_no_sms_timeout"
    assert calls["event"] == "auto_cancel_refund_guard_success"


@pytest.mark.asyncio
async def test_global_rental_sweep_auto_cancels_after_restart(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {"details": []}
    order = {
        "_id": "oid-sweep",
        "status": "success",
        "user_id": 55,
        "reseller_id": 66,
        "provider": "herosms",
        "provider_order_id": "hero-sweep",
        "service_id": "paypal:rental",
        "rental_started_at": datetime.now(UTC) - timedelta(seconds=1190),
    }

    async def _fake_list(limit=200):
        return [order]

    async def _fake_get_order(_order_id):
        return order

    async def _fake_sync(*args, **kwargs):
        return {"success": True, "messages": [], "has_sms": False}

    async def _fake_cancel_and_refund(**kwargs):
        calls["cancel"] = kwargs
        return {"success": True}

    async def _fake_log_rental_event(**kwargs):
        calls["event"] = kwargs.get("event")

    async def _fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    monkeypatch.setattr(hb, "list_open_rental_orders_without_sms", _fake_list)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "_sync_rental_sms_snapshot", _fake_sync)
    monkeypatch.setattr(hb, "_cancel_and_refund_rental_order", _fake_cancel_and_refund)
    monkeypatch.setattr(hb, "_log_rental_event", _fake_log_rental_event)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)

    res = await hb.run_rental_protection_sweep(limit=50, alert_threshold_sec=180)
    assert res["checked"] == 1
    assert res["auto_cancelled"] == 1
    assert calls["cancel"]["order_id"] == "oid-sweep"
    assert calls["cancel"]["reason"] == "herosms_global_guard_no_sms_timeout"
    assert calls["event"] == "auto_cancel_refund_global_guard_success"


@pytest.mark.asyncio
async def test_global_rental_sweep_emits_near_cutoff_alert_once(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {"details": []}
    start_dt = datetime.now(UTC) - timedelta(seconds=1100)
    order = {
        "_id": "oid-alert",
        "status": "success",
        "user_id": 77,
        "reseller_id": 88,
        "provider": "herosms",
        "provider_order_id": "hero-alert",
        "service_id": "google:rental",
        "rental_started_at": start_dt,
    }

    async def _fake_list(limit=200):
        return [order]

    async def _fake_get_order(_order_id):
        return order

    async def _fake_sync(*args, **kwargs):
        return {"success": True, "messages": [], "has_sms": False}

    async def _fake_update_order_details(order_id, patch):
        calls["details"].append((order_id, patch))

    monkeypatch.setattr(hb, "list_open_rental_orders_without_sms", _fake_list)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "_sync_rental_sms_snapshot", _fake_sync)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)

    res = await hb.run_rental_protection_sweep(limit=50, alert_threshold_sec=180)
    assert res["checked"] == 1
    assert res["auto_cancelled"] == 0
    assert len(res["alerts"]) == 1
    assert res["alerts"][0]["kind"] == "near_cutoff"
    assert calls["details"][0][1].get("rental_cutoff_alert_sent_at") is not None


def test_coerce_utc_datetime_accepts_iso_z():
    import services.numbers.handlers.core_numbers_buy as hb

    parsed = hb._coerce_utc_datetime("2026-03-19T12:34:56Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.isoformat().startswith("2026-03-19T12:34:56+00:00")


@pytest.mark.asyncio
async def test_textverified_rent_number_follows_nested_reservation_link(monkeypatch):
    from services.numbers.providers.textverified_provider import TextVerifiedProvider

    provider = TextVerifiedProvider()

    async def _fake_auth():
        return "token"

    responses = [
        (200, {"reservations": [{"id": "lr_123", "link": {"method": "GET", "href": "reservation-link"}}], "total": 1.8}, {}),
        (200, {"method": "GET", "href": "reservation-expanded-link"}, {}),
        (
            200,
            {
                "id": "lr_123",
                "number": "2150000000",
                "endsAt": "2026-03-20T06:06:33.212087+00:00",
                "refund": {"canRefund": False, "refundableUntil": "2026-03-19T07:36:33.212087+00:00"},
            },
            {},
        ),
    ]

    async def _fake_request_link(token, link):
        assert token == "token"
        return responses.pop(0)

    class _DummyResp:
        status = 201
        headers = {"Location": "sale-link"}

        async def text(self):
            return ""

        async def json(self):
            return {"method": "GET", "href": "sale-link"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _DummySession:
        def post(self, *args, **kwargs):
            return _DummyResp()

    async def _fake_session():
        return _DummySession()

    monkeypatch.setattr(provider, "_auth", _fake_auth)
    monkeypatch.setattr(provider, "_request_link", _fake_request_link)
    monkeypatch.setattr("services.numbers.providers.textverified_provider.SessionManager.get_session", _fake_session)

    res = await provider.rent_number("google", country="1", duration=24, tv_duration_key="oneDay", tv_is_renewable=False)
    assert res["success"] is True
    assert res["order_id"] == "lr_123"
    assert res["number"] == "2150000000"
    assert res["refund_can_refund"] is False


@pytest.mark.asyncio
async def test_sync_rental_protection_snapshot_updates_deadline_from_provider(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls: dict = {}
    order = {
        "_id": "oid-tv-info",
        "provider": "textverified",
        "provider_order_id": "tv-123",
        "rental_protection_policy": {"provider": "textverified", "safe_cutoff_sec": 60},
    }

    async def _fake_info(provider_code, activation_id):
        assert provider_code == "textverified"
        assert activation_id == "tv-123"
        return {
            "success": True,
            "refund_can_refund": True,
            "refund_refundable_until": "2026-03-19T12:34:56Z",
            "end_date": "2026-03-20T12:34:56Z",
            "raw": {"ok": 1},
        }

    async def _fake_update_order_details(order_id, patch):
        calls["order_id"] = order_id
        calls["patch"] = patch

    monkeypatch.setattr(hb, "get_rental_info_from_provider", _fake_info)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_order_details)

    res = await hb._sync_rental_protection_snapshot("oid-tv-info", order)
    assert res["success"] is True
    assert calls["order_id"] == "oid-tv-info"
    assert calls["patch"]["rental_refund_deadline_at"].isoformat().startswith("2026-03-19T12:34:56+00:00")
    assert calls["patch"]["rental_provider_can_refund"] is True


@pytest.mark.asyncio
async def test_rental_provider_grid_textverified_routes_to_renew(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb
    from services.numbers.states.core_numbers_states import NumberFlow

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    monkeypatch.setattr(hb, "get_user", _fake_get_user)

    class _DummyMessage:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, reply_markup=None):
            self.edits.append((text, reply_markup))

    class _DummyState:
        def __init__(self):
            self.data = {
                "rental_provider_options": {
                    "textverified": [
                        {
                            "provider": "textverified",
                            "duration": 24,
                            "price": 2.0,
                            "tv_is_renewable": False,
                            "tv_duration_key": "oneDay",
                        },
                        {
                            "provider": "textverified",
                            "duration": 24,
                            "price": 2.5,
                            "tv_is_renewable": True,
                            "tv_duration_key": "oneDay",
                        },
                    ]
                },
                "usd_to_syp_rate": 100.0,
            }
            self.last_state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, new_state):
            self.last_state = new_state

    callback = type(
        "CB",
        (),
        {
            "data": "rentpick:textverified:24",
            "from_user": type("U", (), {"id": 5})(),
            "message": _DummyMessage(),
        },
    )()
    state = _DummyState()

    await hb.rental_option_selected_from_provider_grid(callback, state)

    assert state.last_state == NumberFlow.rental_tv_renew
    assert state.data["tv_selected_duration"] == "oneDay"
    assert callback.message.edits


@pytest.mark.asyncio
async def test_rental_cancel_returns_to_main_menu(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls = {}

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_return(callback, state, lang):
        calls["lang"] = lang

    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_return_to_main_menu_from_buy", _fake_return)

    class _DummyState:
        pass

    class _DummyCallback:
        def __init__(self):
            self.from_user = type("U", (), {"id": 7})()
            self.message = object()

        async def answer(self):
            calls["answered"] = True

    await hb.rental_cancel(_DummyCallback(), _DummyState())
    assert calls["lang"] == "en"
    assert calls["answered"] is True


@pytest.mark.asyncio
async def test_unprovisioned_number_order_recovery_refunds(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls = {}
    old_order = {
        "_id": "oid-paid",
        "user_id": 12,
        "reseller_id": 34,
        "status": "paid",
        "number_mode": "temp",
        "created_at": datetime.now(UTC) - timedelta(minutes=10),
        "selling_price": 2.0,
        "base_price": 1.0,
    }

    async def _fake_list(limit=100):
        return [old_order]

    class _DummyFinancialManager:
        @classmethod
        async def refund_core_purchase(cls, user_id, order_id, sale_price, cost_price, reseller_id=None):
            calls["refund"] = (user_id, order_id, sale_price, cost_price, reseller_id)
            return True, "OK"

    async def _fake_update_status(order_id, status):
        calls["status"] = (order_id, status)

    async def _fake_update_details(order_id, patch):
        calls["details"] = (order_id, patch)

    monkeypatch.setattr(hb, "list_paid_number_orders_missing_provider", _fake_list)
    monkeypatch.setattr(hb, "FinancialManager", _DummyFinancialManager)
    monkeypatch.setattr(hb, "update_order_status", _fake_update_status)
    monkeypatch.setattr(hb, "update_order_details", _fake_update_details)

    stats = await hb.run_unprovisioned_number_order_recovery_sweep(limit=10, grace_sec=30)
    assert stats["refunded"] == 1
    assert calls["status"] == ("oid-paid", "refunded")


@pytest.mark.asyncio
async def test_temp_wait_recovery_syncs_waiting_orders(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb
    import services.numbers.handlers.recovery_runtime as rr

    calls = {}
    order = {
        "_id": "oid-temp",
        "user_id": 21,
        "status": "success",
        "number_mode": "temp",
        "provider": "smsman",
        "provider_sms_delivery": "polling",
        "provider_order_id": "prov-1",
        "telegram_bot_id": 999,
        "temp_wait_state": "waiting",
        "temp_wait_chat_id": 1,
        "temp_wait_message_id": 2,
        "created_at": datetime.now(UTC) - timedelta(minutes=1),
    }

    async def _fake_list(limit=200):
        return [order]

    async def _fake_get_order(_order_id):
        return dict(order)

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_fetch(provider_code, provider_order_id):
        return {"success": True, "messages": []}

    async def _fake_sync(bot, current, lang):
        calls["synced"] = (current["_id"], lang, getattr(bot, "_cached_bot_id", None))

    class _DummyBot:
        _cached_bot_id = 999

    monkeypatch.setattr(hb, "list_open_temp_orders_for_recovery", _fake_list)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_fetch_provider_sms", _fake_fetch)
    monkeypatch.setattr(hb, "_sync_temp_wait_controls", _fake_sync)
    monkeypatch.setattr(rr, "provider_sms_polling_enabled", lambda: True)

    stats = await hb.run_temp_wait_recovery_sweep(bot=_DummyBot(), limit=10)
    assert stats["synced"] == 1
    assert calls["synced"][0] == "oid-temp"


@pytest.mark.asyncio
async def test_temp_recovery_skips_provider_polling_for_webhook_sms(monkeypatch):
    import services.numbers.handlers.core_numbers_buy as hb

    calls = {}
    order = {
        "_id": "oid-temp",
        "status": "success",
        "number_mode": "temp",
        "provider": "smsready",
        "provider_sms_delivery": "webhook",
        "provider_order_id": "50",
        "telegram_bot_id": 999,
        "temp_wait_state": "waiting",
        "temp_wait_chat_id": 1,
        "temp_wait_message_id": 2,
        "created_at": datetime.now(UTC) - timedelta(minutes=1),
    }

    async def _fake_list(limit=200):
        return [order]

    async def _fake_get_order(_order_id):
        return dict(order)

    async def _fake_get_user(_user_id):
        return {"language": "en"}

    async def _fake_fetch(provider_code, provider_order_id):
        calls["fetch"] = (provider_code, provider_order_id)
        return {"success": True, "messages": ["123456"]}

    class _DummyBot:
        _cached_bot_id = 999

    monkeypatch.setattr(hb, "list_open_temp_orders_for_recovery", _fake_list)
    monkeypatch.setattr(hb, "get_order", _fake_get_order)
    monkeypatch.setattr(hb, "get_user", _fake_get_user)
    monkeypatch.setattr(hb, "_fetch_provider_sms", _fake_fetch)

    stats = await hb.run_temp_wait_recovery_sweep(bot=_DummyBot(), limit=10)

    assert stats["webhook_waiting"] == 1
    assert "fetch" not in calls
